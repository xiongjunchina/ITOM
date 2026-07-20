"""M38 UI 品牌配置：公开降级、草稿发布、版本回滚与资源安全。"""

from io import BytesIO

from PIL import Image


def test_public_default_needs_no_login(client):
    response = client.get("/api/public/ui-branding")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "default"
    assert data["config"]["brand"]["system_name_zh"] == "IT运营管理平台"


def test_draft_publish_and_rollback(client, admin_headers):
    admin = client.get("/api/admin/ui-branding", headers=admin_headers).json()["data"]
    config = admin["draft"]["config"]
    config["brand"]["system_name_zh"] = "星云 IT 运营中心"
    saved = client.put("/api/admin/ui-branding/draft", json={"config": config}, headers=admin_headers)
    assert saved.status_code == 200, saved.text
    first = client.post("/api/admin/ui-branding/publish", headers=admin_headers).json()["data"]
    assert first["version"] == 1
    assert client.get("/api/public/ui-branding").json()["data"]["config"]["brand"]["system_name_zh"] == "星云 IT 运营中心"

    config["brand"]["system_name_zh"] = "第二版"
    client.put("/api/admin/ui-branding/draft", json={"config": config}, headers=admin_headers)
    second = client.post("/api/admin/ui-branding/publish", headers=admin_headers).json()["data"]
    assert second["version"] == 2
    rolled = client.post("/api/admin/ui-branding/rollback/1", headers=admin_headers).json()["data"]
    assert rolled["version"] == 3
    assert rolled["config"]["brand"]["system_name_zh"] == "星云 IT 运营中心"


def test_asset_rejects_untrusted_type(client, admin_headers):
    response = client.post(
        "/api/admin/ui-branding/assets?kind=logo_light",
        files={"file": ("logo.svg", b"<svg><script>alert(1)</script></svg>", "image/svg+xml")},
        headers=admin_headers,
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_FILE_TYPE"


def test_cropped_png_upload_preserves_output_dimensions(client, admin_headers):
    buffer = BytesIO()
    Image.new("RGBA", (1200, 300), (36, 87, 214, 255)).save(buffer, format="PNG")
    response = client.post(
        "/api/admin/ui-branding/assets?kind=logo_light",
        files={"file": ("logo-cropped.png", buffer.getvalue(), "image/png")}, headers=admin_headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["width"] == 1200
    assert response.json()["data"]["height"] == 300
