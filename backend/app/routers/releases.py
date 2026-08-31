"""Public, sanitized software release information."""

from fastapi import APIRouter

from app.core.release_info import current_release, release_catalog
from app.schemas.common import ok


router = APIRouter(prefix="/api/public/releases", tags=["software-releases"])


@router.get("/current")
def get_current_release():
    return ok(current_release().public_payload())


@router.get("")
def list_releases():
    rows = [release.public_payload() for release in release_catalog()]
    return ok(rows, total=len(rows))
