#!/usr/bin/env bash
# Deploy ITOM to the SN IDC cluster (namespace: itom).
# Assumes the two app images are already in Harbor (run ./push-images.sh first).
#
# Usage:  cd deploy/k8s && ./k8s-deploy.sh
#
# Prereqs: VPN up + a valid Rancher token in ~/.kube/{sn-rancher.yaml,sn-prod-ip.conf}.
set -euo pipefail
cd "$(dirname "$0")"

NS=itom
SRC_NS=sn-cloud-production            # source of the harbor pull secret + wildcard TLS
SERVER=https://10.60.65.1/k8s/clusters/local

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

echo "==> Namespace"
"${KC[@]}" apply -f 00-namespace.yaml

echo "==> Copy harbor pull secret + wildcard TLS into $NS (from $SRC_NS)"
copy_secret() {  # $1 = secret name
  "${KC[@]}" -n "$SRC_NS" get secret "$1" -o json \
    | python3 -c 'import sys,json; d=json.load(sys.stdin); m=d["metadata"]; [m.pop(k,None) for k in ("namespace","resourceVersion","uid","creationTimestamp","managedFields","ownerReferences","selfLink","generation")]; a=m.get("annotations") or {}; a.pop("kubectl.kubernetes.io/last-applied-configuration",None); m["annotations"]=a; d.pop("status",None); print(json.dumps(d))' \
    | "${KC[@]}" -n "$NS" apply -f -
}
copy_secret harbor-isa
copy_secret wildcard-prod-sn-local-tls

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

echo "==> Apply Postgres, backend, frontend, ingress"
"${KC[@]}" apply -f 10-postgres.yaml
"${KC[@]}" apply -f 20-backend.yaml
"${KC[@]}" apply -f 30-frontend.yaml
"${KC[@]}" apply -f 40-ingress.yaml

echo "==> Wait for Postgres"
"${KC[@]}" -n "$NS" rollout status statefulset/itom-db --timeout=180s || true

echo "==> Wait for backend (first boot runs schema create + seed)"
"${KC[@]}" -n "$NS" rollout status deploy/itom-backend --timeout=240s || true

# Self-heal the flaky cluster CNI: a pod that drew an unreachable Flannel IP
# fails readiness and never joins Endpoints. Recreate such pods a few times.
echo "==> Ensuring Ready endpoints (self-heal past flaky-CNI bad pod IPs)"
for dep in itom-backend itom-frontend; do
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
  [ -n "$ok" ] && echo "   $svc endpoints: $eps" || echo "   !! $svc still has no Ready endpoint — check: ${KC[*]} -n $NS get pods,endpoints -l app=$dep -o wide"
done

echo "==> Status"
"${KC[@]}" -n "$NS" get pods,svc,ingress -o wide 2>&1 | grep -v "Unhandled Error"
echo "==> Done. If DNS+ingress are healthy: https://itom.prod.sn.local"
