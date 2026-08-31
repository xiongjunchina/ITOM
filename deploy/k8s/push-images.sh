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
#   BUILD_SCOPE=frontend ./push-images.sh  # build/push frontend only
#   BUILD_SCOPE=backend ./push-images.sh   # build/push backend only
#
# The default immutable tag is derived from the current Git commit. This script
# builds images only; it never starts a local ITOM application environment.
set -euo pipefail
cd "$(dirname "$0")"

REPO_ROOT="$(git rev-parse --show-toplevel)"
COMMIT_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
python3 "$REPO_ROOT/scripts/validate-release.py"
RELEASE_FILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["current"])' "$REPO_ROOT/release/current.json")"
RELEASE_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release"]["version"])' "$REPO_ROOT/release/releases/$RELEASE_FILE")"
RELEASE_DATE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release"]["release_date"] + "T00:00:00Z")' "$REPO_ROOT/release/releases/$RELEASE_FILE")"
TAG="${TAG:-git-${COMMIT_SHA:0:12}-linux-amd64}"
REG=core.harbor.domain
PYTHON_BASE_IMAGE="${PYTHON_BASE_IMAGE:-mirror.gcr.io/library/python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de}"
NODE_BASE_IMAGE="${NODE_BASE_IMAGE:-mirror.gcr.io/library/node:22-alpine@sha256:c610fcdfb1d5b4740dd70c284ed3cb16bb857e0f7166196e36a5501df7a3aa32}"
NGINX_BASE_IMAGE="${NGINX_BASE_IMAGE:-mirror.gcr.io/library/nginx:1.27-alpine@sha256:65645c7bb6a0661892a8b03b89d0743208a18dd2f3f17a54ef4b76fb8e2f2a10}"
POSTGRES_BASE_IMAGE="${POSTGRES_BASE_IMAGE:-mirror.gcr.io/library/postgres@sha256:7a396fd264a2067788b6551122b50f162bf6136312c7fc9d74381cb92c648382}"
BUILD_SCOPE="${BUILD_SCOPE:-all}"
MIRROR_POSTGRES="${MIRROR_POSTGRES:-0}"

case "$TAG" in
  ""|*[!A-Za-z0-9_.-]*)
    echo "!! Invalid image tag: $TAG"
    exit 1
    ;;
esac

case "$BUILD_SCOPE" in
  all|backend|frontend) ;;
  *) echo "!! BUILD_SCOPE must be all, backend, or frontend"; exit 1 ;;
esac
case "$MIRROR_POSTGRES" in
  0|1) ;;
  *) echo "!! MIRROR_POSTGRES must be 0 or 1"; exit 1 ;;
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
echo "==> Product version: v$RELEASE_VERSION"
echo "==> Immutable image tag: $TAG"
echo "==> Build scope: $BUILD_SCOPE"
if [ "$BUILD_SCOPE" = all ] || [ "$BUILD_SCOPE" = backend ]; then
  docker build --platform linux/amd64 --pull --no-cache \
    --build-arg "PYTHON_BASE_IMAGE=$PYTHON_BASE_IMAGE" \
    --build-arg "APP_VERSION=$RELEASE_VERSION" \
    --build-arg "VCS_REF=$COMMIT_SHA" \
    --build-arg "RELEASE_DATE=$RELEASE_DATE" \
    -f "$REPO_ROOT/backend/Dockerfile" \
    -t "$REG/sn/itom-backend:$TAG" "$REPO_ROOT"
fi
if [ "$BUILD_SCOPE" = all ] || [ "$BUILD_SCOPE" = frontend ]; then
  docker build --platform linux/amd64 --pull --no-cache \
    --build-arg "NODE_BASE_IMAGE=$NODE_BASE_IMAGE" \
    --build-arg "NGINX_BASE_IMAGE=$NGINX_BASE_IMAGE" \
    --build-arg "APP_VERSION=$RELEASE_VERSION" \
    --build-arg "VCS_REF=$COMMIT_SHA" \
    --build-arg "RELEASE_DATE=$RELEASE_DATE" \
    -f "$REPO_ROOT/frontend/Dockerfile" \
    -t "$REG/sn/itom-frontend:$TAG" "$REPO_ROOT"
fi

images=()
if [ "$BUILD_SCOPE" = all ] || [ "$BUILD_SCOPE" = backend ]; then images+=(itom-backend); fi
if [ "$BUILD_SCOPE" = all ] || [ "$BUILD_SCOPE" = frontend ]; then images+=(itom-frontend); fi
for image in "${images[@]}"; do
  arch="$(docker image inspect "$REG/sn/$image:$TAG" --format '{{.Architecture}}')"
  [ "$arch" = "amd64" ] || {
    echo "!! $image:$TAG architecture is $arch, expected amd64"
    exit 1
  }
  version="$(docker image inspect "$REG/sn/$image:$TAG" --format '{{index .Config.Labels "org.opencontainers.image.version"}}')"
  [ "$version" = "$RELEASE_VERSION" ] || {
    echo "!! $image:$TAG product version is $version, expected $RELEASE_VERSION"
    exit 1
  }
  echo "   $image:$TAG architecture: $arch"
  echo "   $image:$TAG product version: $version"
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

for image in "${images[@]}"; do
  echo "==> Push $image"
  skopeo copy --all --src-daemon-host "$DOCKER_DAEMON_HOST" --dest-tls-verify=false --dest-creds "$CREDS" \
    "docker-daemon:$REG/sn/$image:$TAG" "docker://$REG/sn/$image:$TAG"
done

if [ "$MIRROR_POSTGRES" = 1 ]; then
  echo "==> Mirror pinned postgres:16-alpine (amd64)"
  skopeo copy --override-arch amd64 --override-os linux \
    --src-tls-verify=false --dest-tls-verify=false --dest-creds "$CREDS" \
    "docker://$POSTGRES_BASE_IMAGE" docker://$REG/sn/postgres:16-alpine
fi

echo "==> Verify in Harbor"
verify_images=()
for image in "${images[@]}"; do verify_images+=("$image:$TAG"); done
if [ "$MIRROR_POSTGRES" = 1 ]; then verify_images+=(postgres:16-alpine); fi
for rt in "${verify_images[@]}"; do
  skopeo inspect --tls-verify=false --creds "$CREDS" docker://$REG/sn/$rt >/dev/null \
    && echo "   sn/$rt OK" || echo "   !! sn/$rt MISSING"
done
echo "==> Done. Deploy the same immutable tag with:"
if [ "$BUILD_SCOPE" = all ]; then
  echo "    TAG=$TAG ./k8s-deploy.sh"
else
  echo "    DEPLOY_SCOPE=$BUILD_SCOPE SKIP_DATABASE=1 TAG=$TAG ./k8s-deploy.sh"
fi
