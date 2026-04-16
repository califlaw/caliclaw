from __future__ import annotations

import pytest
import pytest_asyncio

from monitoring.tracking import UsageTracker


@pytest_asyncio.fixture
async def tracker(db):
    return UsageTracker(db)


@pytest.mark.asyncio
async def test_log_request(tracker):
    await tracker.log_request("main", "sonnet", duration_ms=5000)
    summary = await tracker.get_today_summary()
    assert summary["total_requests"] == 1


@pytest.mark.asyncio
async def test_today_summary(tracker, db):
    await db.log_usage("main", "sonnet", duration_ms=1000)
    await db.log_usage("main", "haiku", duration_ms=500)

    summary = await tracker.get_today_summary()
    assert summary["total_requests"] == 2
    assert summary["total_duration_ms"] == 1500
    assert "sonnet" in summary["by_model"]
    assert "haiku" in summary["by_model"]
    assert summary["by_model"]["sonnet"]["count"] == 1
