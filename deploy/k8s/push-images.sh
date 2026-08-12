#!/usr/bin/env bash
# Build linux/amd64 ITOM images from a clean commit, then push them
# (+ mirror postgres) into SN Harbor, project `sn`.
#
# Auth: reuses the Harbor credential already stored in-cluster as the
# `harbor-isa` pull secret (read via kubectl), so no token needs to be typed.
# Requires: /etc/hosts maps `core.harbor.domain -> 10.60.65.10` (Harbor's token
# realm redirects to that hostname), Docker, and skopeo.
#
# Usage:
#   ./push-images.sh
#   TAG=release-name-linux-amd64 ./push-images.sh
#
# The default immutable tag is derived from the current Git commit. This script
# builds images only; it never starts a local ITOM application environment.
set -euo pipefail
cd "$(dirname "$0")"

REPO_ROOT="$(git rev-parse --show-toplevel)"
COMMIT_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
TAG="${TAG:-git-${COMMIT_SHA:0:12}-linux-amd64}"
REG=core.harbor.domain
PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-mirror.gcr.io/library/python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de}"
NODE_BASE_IMAGE="${NODE_BASE_IMAGE:-mirror.gcr.io/library/node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32}"
NGINX_BASE_IMAGE="${NGINX_BASE_IMAGE:-mirror.gcr.io/library/nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10}"
POSTGRES_BASE_IMAGE="${POSTGRES_BASE_IMAGE:-mirror.gcr.io/library/postgres@sha256:7a396fd264a2067788b6551122b50f162bf6136312c7fc9d74381cb92c648382}"

case "$TAG" in
  ""|*[!A-Za-z0-9_.-]*)
    echo "!! Invalid image tag: $TAG"
    exit 1
    ;;
esac

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "!! Refusing to publish images from a dirty worktree. Commit the complete implementation, tests, and documentation first."
  exit 1
fi

command -v docker >/dev/null || { echo "!! docker not found"; exit 1; }
command -v skopeo >/dev/null || { echo "!! skopeo not found (brew install skopeo)"; exit 1; }
getent hosts "$REG" >/dev/null 2>&1 || grep -q "$REG" /etc/hosts 2>/dev/null || \
  ping -c1 -t1 "$REG" >/dev/null 2>&1 || { echo "!! $REG does not resolve — add: echo '10.60.65.10 $REG' | sudo tee -a /etc/hosts"; exit 1; }

# `skopeo docker-daemon:` does not honor Docker CLI contexts automatically.
# Resolve the active context explicitly so OrbStack/Colima/Rancher Desktop and
# the default /var/run/docker.sock daemon all use the same release path.
DOCKER_DAEMON_HOST="${DOCKER_DAEMON_HOST:-$(docker context inspect --format '{{.Endpoints.docker.Host}}' 2>/dev/null || true)}"
[ -n "$DOCKER_DAEMON_HOST" ] || { echo "!! Could not resolve the active Docker daemon host"; exit 1; }

echo "==> Release commit: $COMMIT_SHA"
echo "==> Immutable image tag: $TAG"
echo "==> Build backend + frontend for linux/amd64 from pinned base digests (no local app startup)"
docker build --platform linux/amd64 --pull --no-cache \
  --build-arg "PYTHON_BASE_IMAGE=$PYTHON_BASE_IMAGE" \
  -t "$REG/sn/itom-backend:$TAG" "$REPO_ROOT/backend"
docker build --platform linux/amd64 --pull --no-cache \
  --build-arg "NODE_BASE_IMAGE=$NODE_BASE_IMAGE" \
  --build-arg "NGINX_BASE_IMAGE=$NGINX_BASE_IMAGE" \
  -t "$REG/sn/itom-frontend:$TAG" "$REPO_ROOT/frontend"

for image in itom-backend itom-frontend; do
  arch="$(docker image inspect "$REG/sn/$image:$TAG" --format '{{.Architecture}}')"
  [ "$arch" = "amd64" ] || {
    echo "!! $image:$TAG architecture is $arch, expected amd64"
    exit 1
  }
  echo "   $image:$TAG architecture: $arch"
done

# ---- cluster auth (freshest Rancher token + IP endpoint) to read the secret ----
newest=""
for f in "$HOME/.kube/sn-rancher.yaml" "$HOME/.kube/sn-prod-ip.conf"; do
  [ -f "$f" ] || continue
  { [ -z "$newest" ] || [ "$f" -nt "$newest" ]; } && newest="$f"
done
KTOK="$(grep -m1 'token:' "$newest" | sed 's/.*token:[[:space:]]*//' | sed 's/[[:space:]"'\'']//g')"
KC=(kubectl --kubeconfig=/dev/null --server=https://10.60.65.1/k8s/clusters/local --insecure-skip-tls-verify --token="$KTOK" --request-timeout=25s)

# ---- Harbor creds from the harbor-isa pull secret (never printed) ----
eval "$("${KC[@]}" -n sn-cloud-production get secret harbor-isa \
  -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | python3 -c '
import sys,json,shlex,base64 as b64
d=json.load(sys.stdin)
for host,v in d.get("auths",{}).items():
    u=v.get("username"); p=v.get("password")
    if not p and v.get("auth"): u,p=b64.b64decode(v["auth"]).decode().split(":",1)
    print("HU="+shlex.quote(u)); print("HP="+shlex.quote(p)); break
')"
[ -n "${HU:-}" ] && [ -n "${HP:-}" ] || { echo "!! could not read Harbor creds from harbor-isa"; exit 1; }
CREDS="$HU:$HP"

echo "==> Validate creds (read-only inspect of an existing image)"
skopeo inspect --tls-verify=false --creds "$CREDS" docker://$REG/sn/aom-gateway:547ccd8 >/dev/null \
  || { echo "!! cred/connectivity check failed — NOT pushing (avoids admin lockout)"; exit 1; }

echo "==> Push backend"
skopeo copy --all --src-daemon-host "$DOCKER_DAEMON_HOST" --dest-tls-verify=false --dest-creds "$CREDS" \
  docker-daemon:$REG/sn/itom-backend:$TAG docker://$REG/sn/itom-backend:$TAG

echo "==> Push frontend"
skopeo copy --all --src-daemon-host "$DOCKER_DAEMON_HOST" --dest-tls-verify=false --dest-creds "$CREDS" \
  docker-daemon:$REG/sn/itom-frontend:$TAG docker://$REG/sn/itom-frontend:$TAG

echo "==> Mirror pinned postgres:16-alpine (amd64) so air-gapped nodes can pull it"
skopeo copy --override-arch amd64 --override-os linux \
  --src-tls-verify=false --dest-tls-verify=false --dest-creds "$CREDS" \
  "docker://$POSTGRES_BASE_IMAGE" docker://$REG/sn/postgres:16-alpine

echo "==> Verify in Harbor"
for rt in itom-backend:$TAG itom-frontend:$TAG postgres:16-alpine; do
  skopeo inspect --tls-verify=false --creds "$CREDS" docker://$REG/sn/$rt >/dev/null \
    && echo "   sn/$rt OK" || echo "   !! sn/$rt MISSING"
done
echo "==> Done. Deploy the same immutable tag with:"
echo "    TAG=$TAG ./k8s-deploy.sh"
