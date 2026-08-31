import pytest

from app.core.release_info import clear_release_cache, current_release, release_catalog


def test_public_release_endpoints_are_sanitized(client):
    current = client.get("/api/public/releases/current")
    assert current.status_code == 200
    payload = current.json()["data"]
    assert payload["release"]["version"] == "1.2.0-rc.1"
    assert payload["notes"]["zh"]["highlights"]
    def collect_keys(value):
        if isinstance(value, dict):
            return set(value) | set().union(*(collect_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(collect_keys(item) for item in value))
        return set()

    keys = collect_keys(payload)
    for private_field in ("git_sha", "image", "digest", "database_change", "minimum_rollback_version"):
        assert private_field not in keys

    catalog = client.get("/api/public/releases")
    assert catalog.status_code == 200
    assert catalog.json()["total"] >= 1
    assert catalog.json()["data"][0]["release"]["version"] == payload["release"]["version"]


def test_health_and_openapi_use_current_product_version(client):
    expected = current_release().release.version
    assert client.get("/api/health").json()["data"]["version"] == expected
    assert client.get("/api/openapi.json").json()["info"]["version"] == expected


def test_release_pointer_rejects_path_traversal(tmp_path, monkeypatch):
    (tmp_path / "releases").mkdir()
    (tmp_path / "current.json").write_text(
        '{"schema_version": 1, "current": "../outside.json"}', encoding="utf-8"
    )
    monkeypatch.setenv("ITOM_RELEASE_DIR", str(tmp_path))
    clear_release_cache()
    try:
        with pytest.raises(ValueError, match="safe JSON filename"):
            current_release()
    finally:
        monkeypatch.delenv("ITOM_RELEASE_DIR")
        clear_release_cache()


def test_catalog_and_current_manifest_are_consistent():
    current = current_release()
    catalog = release_catalog()
    assert current.release.version in {item.release.version for item in catalog}
    assert all(item.product.code == "itom" for item in catalog)
