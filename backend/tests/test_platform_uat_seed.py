from datetime import date

import pytest

from app.db import SessionLocal
from app.models import PlatformCapacityCommitment, PlatformCapacityPlan, PlatformDemandProfile, PlatformServiceProfile
from app.services.seed_platform_uat import cleanup_platform_uat, seed_platform_uat
from app.scripts.verify_platform_uat import assert_local_api_base, next_quarter


def test_platform_uat_verifier_is_local_only_and_rolls_quarters():
    assert_local_api_base("http://127.0.0.1:6800")
    assert_local_api_base("http://localhost:18180")
    with pytest.raises(RuntimeError, match="只允许调用本地"):
        assert_local_api_base("https://itom.example.com")
    assert next_quarter(date(2026, 8, 31)) == "2026-Q4"
    assert next_quarter(date(2026, 12, 31)) == "2027-Q1"


def test_platform_uat_seed_is_local_idempotent_and_cleanable(client):
    with SessionLocal() as db:
        first = seed_platform_uat(db)
        second = seed_platform_uat(db)
        assert first == second == {"services": 1, "demands": 6, "plans": 2, "commitments": 5}
        assert db.query(PlatformServiceProfile).filter(PlatformServiceProfile.is_deleted.is_(False)).count() == 1
        assert db.query(PlatformDemandProfile).filter(PlatformDemandProfile.is_deleted.is_(False)).count() == 6
        assert db.query(PlatformCapacityPlan).filter(PlatformCapacityPlan.is_deleted.is_(False)).count() == 2
        assert db.query(PlatformCapacityCommitment).filter(PlatformCapacityCommitment.is_deleted.is_(False)).count() == 5

        removed = cleanup_platform_uat(db)
        assert removed == {"services": 1, "demands": 6, "plans": 2, "commitments": 5, "users": 1}
        assert db.query(PlatformServiceProfile).filter(PlatformServiceProfile.is_deleted.is_(False)).count() == 0

        reseeded = seed_platform_uat(db)
        assert reseeded == first
