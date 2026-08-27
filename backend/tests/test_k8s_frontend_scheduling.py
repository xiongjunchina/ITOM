"""Regression contracts for ITOM's multi-node frontend deployment."""

from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def test_frontend_prefers_host_spread_without_a_hard_node_pin():
    """Two web replicas should spread when possible but recover on one node."""
    manifest = (REPOSITORY_ROOT / "deploy/k8s/30-frontend.yaml").read_text()

    assert "nodeSelector:" not in manifest
    assert "topologySpreadConstraints:" in manifest
    assert "maxSkew: 1" in manifest
    assert "topologyKey: kubernetes.io/hostname" in manifest
    assert "whenUnsatisfiable: ScheduleAnyway" in manifest
    assert "matchLabels: { app: itom-frontend }" in manifest


def test_release_script_checks_every_ready_frontend_proxy():
    """A rollout must not validate only one of the distributed web replicas."""
    deploy_script = (REPOSITORY_ROOT / "deploy/k8s/k8s-deploy.sh").read_text()

    assert 'front_pods="$("${KC[@]}" -n "$NS" get endpoints itom-frontend' in deploy_script
    assert "for front_pod in $front_pods; do" in deploy_script
    assert 'echo "   $front_pod proxy health: OK"' in deploy_script
