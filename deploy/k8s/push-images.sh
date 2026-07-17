#!/usr/bin/env bash
# Push ITOM images (+ mirror postgres) into SN Harbor, project `sn`.
#
# Auth: reuses the Harbor credential already stored in-cluster as the
# `harbor-isa` pull secret (read via kubectl), so no token needs to be typed.
# Requires: /etc/hosts maps `core.harbor.domain -> 10.60.65.10` (Harbor's token
# realm redirects to that hostname), and skopeo installed.
#
# Usage:  ./push-images.sh
set -euo pipefail
cd "$(dirname "$0")"
TAG=87b8f90b
REG=core.harbor.domain

command -v skopeo >/dev/null || { echo "!! skopeo not found (brew install skopeo)"; exit 1; }
getent hosts "$REG" >/dev/null 2>&1 || grep -q "$REG" /etc/hosts 2>/dev/null || \
  ping -c1 -t1 "$REG" >/dev/null 2>&1 || { echo "!! $REG does not resolve — add: echo '10.60.65.10 $REG' | sudo tee -a /etc/hosts"; exit 1; }

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
skopeo copy --all --dest-tls-verify=false --dest-creds "$CREDS" \
  docker-daemon:$REG/sn/itom-backend:$TAG docker://$REG/sn/itom-backend:$TAG

echo "==> Push frontend"
skopeo copy --all --dest-tls-verify=false --dest-creds "$CREDS" \
  docker-daemon:$REG/sn/itom-frontend:$TAG docker://$REG/sn/itom-frontend:$TAG

echo "==> Mirror postgres:16-alpine (amd64) so air-gapped nodes can pull it"
skopeo copy --override-arch amd64 --override-os linux \
  --src-tls-verify=false --dest-tls-verify=false --dest-creds "$CREDS" \
  docker://docker.io/library/postgres:16-alpine docker://$REG/sn/postgres:16-alpine

echo "==> Verify in Harbor"
for rt in itom-backend:$TAG itom-frontend:$TAG postgres:16-alpine; do
  skopeo inspect --tls-verify=false --creds "$CREDS" docker://$REG/sn/$rt >/dev/null \
    && echo "   sn/$rt OK" || echo "   !! sn/$rt MISSING"
done
echo "==> Done. Next: ./k8s-deploy.sh"
