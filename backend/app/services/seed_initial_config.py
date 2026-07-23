"""可复制部署的初始流程与品牌配置。

流程定义本身由 :mod:`seed_itsm` 负责幂等创建；本模块补齐一个新环境没有用户
操作历史时仍需要的品牌资源和发布快照。初始化只在没有任何已发布/草稿品牌配置
时执行，绝不会覆盖管理员后来在界面保存的配置。
"""

from __future__ import annotations

import os
import shutil
from copy import deepcopy
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.glid import new_glid
from app.models import UiBrandingAsset, UiBrandingVersion
from app.services.ui_branding import DEFAULT_UI_BRANDING


_ASSET_DIR = Path(__file__).resolve().parents[1] / "assets" / "branding"
_ASSETS = {
    "logo_light": ("logo_light.png", "image/png"),
    "logo_dark": ("logo_dark.png", "image/png"),
    "logo_square": ("logo_square.png", "image/png"),
    "favicon": ("favicon.png", "image/png"),
}


def _copy_asset(kind: str, filename: str, content_type: str, db: Session) -> str | None:
    """复制打包资源到上传卷并返回公开 URL；资源缺失时跳过而不阻断启动。"""

    source = _ASSET_DIR / filename
    if not source.is_file():
        return None

    target_dir = Path(settings.upload_dir) / "ui-branding"
    target_dir.mkdir(parents=True, exist_ok=True)
    # 用固定文件名避免每次启动生成孤儿文件；数据库 ID 仍由 GLID 管理。
    existing = (
        db.query(UiBrandingAsset)
        .filter(
            UiBrandingAsset.kind == kind,
            UiBrandingAsset.filename == filename,
            UiBrandingAsset.is_deleted.is_(False),
        )
        .first()
    )
    if existing:
        target = Path(existing.storage_path)
        if not target.is_file():
            shutil.copyfile(source, target)
        return f"/api/public/ui-branding/assets/{existing.id}"

    target = target_dir / filename
    if not target.is_file():
        shutil.copyfile(source, target)
    try:
        from PIL import Image

        with Image.open(target) as image:
            width, height = image.size
    except Exception:
        width = height = None
    asset = UiBrandingAsset(
        id=new_glid(),
        kind=kind,
        filename=filename,
        storage_path=str(target),
        content_type=content_type,
        size=target.stat().st_size,
        width=width,
        height=height,
    )
    db.add(asset)
    db.flush()
    return f"/api/public/ui-branding/assets/{asset.id}"


def seed_initial_branding(db: Session) -> bool:
    """在全新环境发布本地已验证的登录页、Logo 和 favicon。"""

    if db.query(UiBrandingVersion).filter(UiBrandingVersion.is_deleted.is_(False)).first():
        return False

    config = deepcopy(DEFAULT_UI_BRANDING)
    # 本地 Docker 当前验证过的登录标题和品牌名称。
    config["login"]["title_zh"] = "IT运营管理平台"
    for kind, (filename, content_type) in _ASSETS.items():
        url = _copy_asset(kind, filename, content_type, db)
        if url:
            config["brand"][f"{kind}_url"] = url

    db.add(
        UiBrandingVersion(
            id=new_glid(),
            version=1,
            status="published",
            config=config,
        )
    )
    db.commit()
    return True


def run_seed_initial_config(db: Session) -> None:
    """按部署开关执行初始配置，默认由 Docker/K8s 清单开启。"""

    if os.getenv("SEED_INITIAL_CONFIG", "0") != "1":
        return
    seed_initial_branding(db)
