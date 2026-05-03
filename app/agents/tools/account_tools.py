from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class BuildSummary:
    build_id: str
    pipeline: str
    status: str
    branch: str
    started_at: datetime
    duration_seconds: int


@dataclass
class AccountStatus:
    user_id: str
    plan_tier: str
    concurrent_builds_used: int
    concurrent_builds_limit: int
    storage_used_gb: float
    storage_limit_gb: float


def _mock_builds_for_user(user_id: str) -> list[BuildSummary]:
    now = datetime.now(tz=UTC)
    return [
        BuildSummary(
            build_id="bld_001",
            pipeline="release",
            status="failed",
            branch="main",
            started_at=now,
            duration_seconds=142,
        ),
        BuildSummary(
            build_id="bld_002",
            pipeline="ci",
            status="failed",
            branch="feature/auth",
            started_at=now,
            duration_seconds=88,
        ),
        BuildSummary(
            build_id="bld_003",
            pipeline="ci",
            status="passed",
            branch="main",
            started_at=now,
            duration_seconds=210,
        ),
    ]


async def get_recent_builds(user_id: str, limit: int = 5) -> list[BuildSummary]:
    builds = _mock_builds_for_user(user_id)
    return builds[: max(limit, 1)]


async def get_account_status(user_id: str) -> AccountStatus:
    return AccountStatus(
        user_id=user_id,
        plan_tier="pro",
        concurrent_builds_used=1,
        concurrent_builds_limit=4,
        storage_used_gb=12.4,
        storage_limit_gb=100.0,
    )
