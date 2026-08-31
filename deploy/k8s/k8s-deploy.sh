#!/usr/bin/env bash
# Deploy ITOM to the SN IDC cluster (namespace: itom).
# Assumes the two app images are already in Harbor (run ./push-images.sh first).
#
# Usage:
#   cd deploy/k8s
#   ./k8s-deploy.sh
#   TAG=release-name-linux-amd64 ./k8s-deploy.sh
#   SKIP_DATABASE=1 ./k8s-deploy.sh  # strict app-only rollout; do not apply/wait for PostgreSQL
#   DEPLOY_SCOPE=frontend SKIP_DATABASE=1 ./k8s-deploy.sh
#
# Prereqs: VPN up + a valid Rancher token in ~/.kube/{sn-rancher.yaml,sn-prod-ip.conf}.
set -euo pipefail
cd "$(dirname "$0")"

REPO_ROOT="$(git rev-parse --show-toplevel)"
COMMIT_SHA="$(git -C "$REPO_ROOT" rev-parse HEAD)"
python3 "$REPO_ROOT/scripts/validate-release.py"
RELEASE_FILE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["current"])' "$REPO_ROOT/release/current.json")"
RELEASE_VERSION="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["release"]["version"])' "$REPO_ROOT/release/releases/$RELEASE_FILE")"
TAG="${TAG:-git-${COMMIT_SHA:0:12}-linux-amd64}"
REG=core.harbor.domain
NS=itom
SRC_NS=sn-cloud-production            # source of the harbor pull secret + wildcard TLS
SERVER=https://10.60.65.1/k8s/clusters/local
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-https://itom.snnc.cc:30443}"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL%/}"
PUBLIC_TLS_SECRET="${PUBLIC_TLS_SECRET:-itom-snnc-cc-tls}"
SKIP_DATABASE="${SKIP_DATABASE:-0}"
DEPLOY_SCOPE="${DEPLOY_SCOPE:-all}"

case "$TAG" in
  ""|*[!A-Za-z0-9_.-]*)
    echo "!! Invalid image tag: $TAG"
    exit 1
    ;;
esac

case "$SKIP_DATABASE" in
  0|1) ;;
  *)
    echo "!! SKIP_DATABASE must be 0 or 1, got: $SKIP_DATABASE"
    exit 1
    ;;
esac
case "$DEPLOY_SCOPE" in
  all|backend|frontend) ;;
  *) echo "!! DEPLOY_SCOPE must be all, backend, or frontend"; exit 1 ;;
esac
if [ "$DEPLOY_SCOPE" != all ] && [ "$SKIP_DATABASE" != 1 ]; then
  echo "!! Component-scoped deployment requires SKIP_DATABASE=1"
  exit 1
fi

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
  echo "!! Refusing to deploy from a dirty worktree. Commit the complete implementation, tests, and documentation first."
  exit 1
fi

echo "==> Release commit: $COMMIT_SHA"
echo "==> Product version: v$RELEASE_VERSION"
echo "==> Deploy image tag: $TAG"
echo "==> Deploy scope: $DEPLOY_SCOPE"
if [ "$SKIP_DATABASE" = "1" ]; then
  echo "==> Database mode: preserve PostgreSQL StatefulSet/PVC; skip database manifest apply and rollout wait"
fi

# ---- cluster auth: freshest token + IP endpoint (DNS endpoint EOFs on VPN) ----
newest=""
for f in "$HOME/.kube/sn-rancher.yaml" "$HOME/.kube/sn-prod-ip.conf"; do
  [ -f "$f" ] || continue
  { [ -z "$newest" ] || [ "$f" -nt "$newest" ]; } && newest="$f"
done
[ -n "$newest" ] || { echo "!! No kubeconfig found"; exit 1; }
TOKEN="$(grep -m1 'token:' "$newest" | sed 's/.*token:[[:space:]]*//' | sed 's/[[:space:]"'\'']//g')"
[ -n "$TOKEN" ] || { echo "!! No token in $newest — re-download kubeconfig"; exit 1; }
KC=(kubectl --kubeconfig=/dev/null --server="$SERVER" --insecure-skip-tls-verify --token="$TOKEN" --request-timeout=40s)
echo "==> auth via $newest"

if [ "$DEPLOY_SCOPE" = all ]; then
  echo "==> Namespace"
  "${KC[@]}" apply -f 00-namespace.yaml

  echo "==> Copy harbor pull secret + wildcard TLS into $NS (from $SRC_NS)"
  copy_secret() {
    "${KC[@]}" -n "$SRC_NS" get secret "$1" -o json \
      | python3 -c 'import sys,json; d=json.load(sys.stdin); m=d["metadata"]; [m.pop(k,None) for k in ("namespace","resourceVersion","uid","creationTimestamp","managedFields","ownerReferences","selfLink","generation")]; a=m.get("annotations") or {}; a.pop("kubectl.kubernetes.io/last-applied-configuration",None); m["annotations"]=a; d.pop("status",None); print(json.dumps(d))' \
      | "${KC[@]}" -n "$NS" apply -f -
  }
  copy_secret harbor-isa
  copy_secret wildcard-prod-sn-local-tls

  echo "==> Verify public TLS Secret in $NS"
  public_tls_type="$("${KC[@]}" -n "$NS" get secret "$PUBLIC_TLS_SECRET" -o jsonpath='{.type}' 2>/dev/null || true)"
  [ "$public_tls_type" = "kubernetes.io/tls" ] || {
    echo "!! Required public TLS Secret $NS/$PUBLIC_TLS_SECRET is missing or is not type kubernetes.io/tls"
    exit 1
  }

  echo "==> App secret (generated once; kept on re-run so the DB password is stable)"
  if ! "${KC[@]}" -n "$NS" get secret itom-secrets >/dev/null 2>&1; then
    DB_PASSWORD="$(openssl rand -hex 24)"
    JWT_SECRET="$(openssl rand -hex 48)"
    ADMIN_INIT_PASSWORD="$(openssl rand -base64 18 | tr -dc 'A-Za-z0-9' | cut -c1-16)"
    DATABASE_URL="postgresql+psycopg2://aom:${DB_PASSWORD}@itom-db:5432/new_aom"
    "${KC[@]}" -n "$NS" create secret generic itom-secrets \
      --from-literal=DB_PASSWORD="$DB_PASSWORD" \
      --from-literal=JWT_SECRET="$JWT_SECRET" \
      --from-literal=ADMIN_INIT_PASSWORD="$ADMIN_INIT_PASSWORD" \
      --from-literal=DATABASE_URL="$DATABASE_URL"
    echo "   ****************************************************************"
    echo "   *  ITOM 初始登录:  用户名 admin   密码 ${ADMIN_INIT_PASSWORD}"
    echo "   *  (登录后请立即修改;此密码只在此显示一次)"
    echo "   ****************************************************************"
  else
    echo "   itom-secrets already exists — keeping current values (DB password unchanged)."
  fi
else
  echo "==> Preserve shared resources (namespace, Secrets, Ingress, PostgreSQL)"
fi

if [ "$SKIP_DATABASE" = "1" ]; then
  echo "==> Preserve PostgreSQL (skip 10-postgres.yaml)"
else
  echo "==> Apply PostgreSQL"
  "${KC[@]}" apply -f 10-postgres.yaml
fi
echo "==> Apply selected immutable app images"
if [ "$DEPLOY_SCOPE" = all ] || [ "$DEPLOY_SCOPE" = backend ]; then
  sed -E "s#(image:[[:space:]]*$REG/sn/itom-backend:)[^[:space:]]+#\\1$TAG#" 20-backend.yaml \
    | "${KC[@]}" apply -f -
fi
if [ "$DEPLOY_SCOPE" = all ] || [ "$DEPLOY_SCOPE" = frontend ]; then
  sed -E "s#(image:[[:space:]]*$REG/sn/itom-frontend:)[^[:space:]]+#\\1$TAG#" 30-frontend.yaml \
    | "${KC[@]}" apply -f -
fi
if [ "$DEPLOY_SCOPE" = all ]; then "${KC[@]}" apply -f 40-ingress.yaml; fi

if [ "$SKIP_DATABASE" = "1" ]; then
  echo "==> Preserve PostgreSQL (skip StatefulSet rollout wait)"
else
  echo "==> Wait for PostgreSQL"
  "${KC[@]}" -n "$NS" rollout status statefulset/itom-db --timeout=180s
fi

if [ "$DEPLOY_SCOPE" = all ] || [ "$DEPLOY_SCOPE" = backend ]; then
  echo "==> Wait for backend (first boot runs schema create + seed)"
  "${KC[@]}" -n "$NS" rollout status deploy/itom-backend --timeout=240s
fi
if [ "$DEPLOY_SCOPE" = all ] || [ "$DEPLOY_SCOPE" = frontend ]; then
  echo "==> Wait for frontend"
  "${KC[@]}" -n "$NS" rollout status deploy/itom-frontend --timeout=180s
fi

# Endpoint recovery: if a rollout has no Ready endpoint, recreate one pending
# pod a bounded number of times before failing the release.
echo "==> Ensuring Ready endpoints"
deps=()
if [ "$DEPLOY_SCOPE" = all ] || [ "$DEPLOY_SCOPE" = backend ]; then deps+=(itom-backend); fi
if [ "$DEPLOY_SCOPE" = all ] || [ "$DEPLOY_SCOPE" = frontend ]; then deps+=(itom-frontend); fi
for dep in "${deps[@]}"; do
  svc="$dep"; [ "$dep" = "itom-backend" ] && svc="backend"
  ok=
  for attempt in 1 2 3 4 5; do
    for i in 1 2 3 4 5 6 7 8; do
      eps="$("${KC[@]}" -n "$NS" get endpoints "$svc" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null)"
      [ -n "$eps" ] && { ok=1; break; }
      sleep 5
    done
    [ -n "$ok" ] && break
    bad="$("${KC[@]}" -n "$NS" get pods -l app="$dep" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)"
    echo "   $dep: no Ready endpoint yet; recreating pod ${bad:-?} ($attempt/5)"
    [ -n "$bad" ] && "${KC[@]}" -n "$NS" delete pod "$bad" --grace-period=3 >/dev/null 2>&1 || true
  done
  if [ -n "$ok" ]; then
    echo "   $svc endpoints: $eps"
  else
    echo "   !! $svc still has no Ready endpoint — check: ${KC[*]} -n $NS get pods,endpoints -l app=$dep -o wide"
    exit 1
  fi
done

echo "==> Verify deployed image identities"
actual_backend="$("${KC[@]}" -n "$NS" get deployment itom-backend -o jsonpath='{.spec.template.spec.containers[0].image}')"
actual_frontend="$("${KC[@]}" -n "$NS" get deployment itom-frontend -o jsonpath='{.spec.template.spec.containers[0].image}')"
if [ "$DEPLOY_SCOPE" = all ] || [ "$DEPLOY_SCOPE" = backend ]; then
  [ "$actual_backend" = "$REG/sn/itom-backend:$TAG" ] || { echo "!! backend image mismatch: $actual_backend"; exit 1; }
fi
if [ "$DEPLOY_SCOPE" = all ] || [ "$DEPLOY_SCOPE" = frontend ]; then
  [ "$actual_frontend" = "$REG/sn/itom-frontend:$TAG" ] || { echo "!! frontend image mismatch: $actual_frontend"; exit 1; }
fi
echo "   backend: $actual_backend"
echo "   frontend: $actual_frontend"

# An endpoint alone is insufficient: nginx can be Ready while cross-node
# DNS/backend access is degraded. Check every Ready frontend endpoint, because
# the web replicas are intentionally spread across Kubernetes hosts.
echo "==> Verify every frontend -> backend proxy"
front_pods="$("${KC[@]}" -n "$NS" get endpoints itom-frontend \
  -o jsonpath='{.subsets[*].addresses[*].targetRef.name}' 2>/dev/null)"
if [ -z "$front_pods" ]; then
  echo "   !! no Ready frontend endpoint"
  exit 1
fi
for front_pod in $front_pods; do
  if ! "${KC[@]}" -n "$NS" exec "$front_pod" -- \
    wget -qO- --timeout=10 http://localhost/api/health | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"'; then
    echo "   !! $front_pod cannot proxy /api/health to backend"
    exit 1
  fi
  echo "   $front_pod proxy health: OK"
done

echo "==> Verify external health and MCP initialize"
curl_args=(--fail --silent --show-error --max-time 20)
if [ "${ALLOW_UNTRUSTED_TLS:-0}" = "1" ]; then
  echo "!! ALLOW_UNTRUSTED_TLS is not permitted for IDC release verification"
  exit 1
fi
health_response="$(curl "${curl_args[@]}" "$PUBLIC_BASE_URL/api/health")"
printf '%s' "$health_response" | grep -Eq '"status"[[:space:]]*:[[:space:]]*"ok"' || {
    echo "   !! external /api/health failed: $PUBLIC_BASE_URL/api/health"
    exit 1
  }
python3 -c 'import json,sys; data=json.loads(sys.argv[1])["data"]; actual=data.get("version"); expected=sys.argv[2]; assert actual == expected, f"{actual} != {expected}"' "$health_response" "$RELEASE_VERSION" || {
  echo "   !! external product version does not match v$RELEASE_VERSION"
  exit 1
}
mcp_response="$(
  curl "${curl_args[@]}" \
    -H 'Origin: https://aily.feishu.cn' \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    --data '{"jsonrpc":"2.0","id":"idc-release-probe","method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"itom-idc-release","version":"1.0"}}}' \
    "$PUBLIC_BASE_URL/mcp/"
)"
printf '%s' "$mcp_response" | grep -q '"serverInfo"' || {
  echo "   !! external MCP initialize did not return serverInfo"
  exit 1
}
echo "   external /api/health: OK"
echo "   external MCP initialize: OK"

echo "==> Status"
"${KC[@]}" -n "$NS" get pods,svc,ingress -o wide 2>&1 | grep -v "Unhandled Error"
echo "==> Done: $PUBLIC_BASE_URL"
