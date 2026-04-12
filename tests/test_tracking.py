from __future__ import annotations

import pytest
import pytest_asyncio

from monitoring.tracking import UsageTracker, ModelRouter


@pytest_asyncio.fixture
async def tracker(db):
    return UsageTracker(db)


@pytest.mark.asyncio
async def test_log_request(tracker):
    total = await tracker.log_request("main", "sonnet", duration_ms=5000)
    assert total > 0


@pytest.mark.asyncio
async def test_check_limits_ok(tracker):
    status = await tracker.check_limits()
    assert status == "ok"


@pytest.mark.asyncio
async def test_check_limits_warning(tracker, db):
    # Log enough to hit warning threshold
    for _ in range(500):
        await db.log_usage("main", "sonnet", estimated_percent=0.2)

    status = await tracker.check_limits()
    assert status in ("warning", "emergency", "stop")


@pytest.mark.asyncio
async def test_today_summary(tracker, db):
    await db.log_usage("main", "sonnet", duration_ms=1000, estimated_percent=0.2)
    await db.log_usage("main", "haiku", duration_ms=500, estimated_percent=0.05)

    summary = await tracker.get_today_summary()
    assert summary["total_requests"] == 2
    assert summary["total_percent"] > 0
    assert "sonnet" in summary["by_model"]
    assert "haiku" in summary["by_model"]


@pytest.mark.asyncio
async def test_model_router_normal(db):
    tracker = UsageTracker(db)
    router = ModelRouter(tracker)

    model = await router.select_model("simple")
    assert model == "haiku"

    model = await router.select_model("coding")
    assert model == "sonnet"

    model = await router.select_model("complex")
    assert model == "opus"


@pytest.mark.asyncio
async def test_model_router_force(db):
    tracker = UsageTracker(db)
    router = ModelRouter(tracker)

    model = await router.select_model("simple", force_model="opus")
    assert model == "opus"


@pytest.mark.asyncio
async def test_model_router_downgrade_on_high_usage(db):
    tracker = UsageTracker(db)
    router = ModelRouter(tracker)

    # Simulate high usage
    for _ in range(500):
        await db.log_usage("main", "sonnet", estimated_percent=0.2)

    model = await router.select_model("complex")
    # Should be downgraded from opus
    assert model in ("sonnet", "haiku")
