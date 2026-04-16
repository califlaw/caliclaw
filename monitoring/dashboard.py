from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from datetime import datetime, timezone

from core.config import get_settings
from core.db import Database
from monitoring.tracking import UsageTracker

logger = logging.getLogger(__name__)

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>caliclaw Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<style>
body {{ font-family: monospace; background: #1a1a2e; color: #e0e0e0; padding: 20px; }}
h1 {{ color: #00d4ff; }}
.card {{ background: #16213e; border-radius: 8px; padding: 16px; margin: 10px 0; }}
.ok {{ color: #00ff88; }} .warn {{ color: #ffaa00; }} .error {{ color: #ff4444; }}
.bar {{ background: #0a0a1a; border-radius: 4px; height: 20px; margin: 4px 0; }}
.bar-fill {{ background: #00d4ff; height: 100%; border-radius: 4px; transition: width 0.5s; }}
.bar-fill.high {{ background: #ffaa00; }}
.bar-fill.critical {{ background: #ff4444; }}
table {{ width: 100%; border-collapse: collapse; }}
td, th {{ padding: 8px; text-align: left; border-bottom: 1px solid #2a2a4e; }}
</style>
</head>
<body>
<h1>caliclaw Status</h1>
<div class="card">
<h3>System</h3>
{system_status}
</div>
<div class="card">
<h3>Activity Today</h3>
<p>{usage_requests} requests</p>
</div>
<div class="card">
<h3>Agents</h3>
<table>{agents_table}</table>
</div>
<div class="card">
<h3>Scheduled Tasks</h3>
<table>{tasks_table}</table>
</div>
<div class="card">
<h3>Recent Activity</h3>
<table>{activity_table}</table>
</div>
<p style="color:#666">Last updated: {updated}</p>
</body>
</html>"""


async def render_dashboard(db: Database) -> str:
    """Render HTML dashboard."""
    tracker = UsageTracker(db)
    summary = await tracker.get_today_summary()

    # Agents
    agents = await db.list_agents()
    agents_rows = ""
    for a in agents:
        agents_rows += f"<tr><td>{a['name']}</td><td>{a['scope']}</td><td class='ok'>{a['status']}</td></tr>"
    if not agents_rows:
        agents_rows = "<tr><td colspan='3'>No agents</td></tr>"

    # Tasks
    async with db.db.execute(
        "SELECT * FROM tasks WHERE status = 'active' ORDER BY next_run LIMIT 10"
    ) as cur:
        tasks = [dict(r) for r in await cur.fetchall()]

    tasks_rows = ""
    for t in tasks:
        next_run = datetime.fromtimestamp(t["next_run"], tz=timezone.utc).strftime("%H:%M") if t["next_run"] else "—"
        tasks_rows += f"<tr><td>{t['name']}</td><td>{t['schedule_value']}</td><td>{next_run}</td></tr>"
    if not tasks_rows:
        tasks_rows = "<tr><td colspan='3'>No active tasks</td></tr>"

    # Recent activity
    async with db.db.execute(
        "SELECT agent_name, model, timestamp, duration_ms FROM usage_log ORDER BY timestamp DESC LIMIT 10"
    ) as cur:
        activity = [dict(r) for r in await cur.fetchall()]

    activity_rows = ""
    for a in activity:
        ts = datetime.fromtimestamp(a["timestamp"], tz=timezone.utc).strftime("%H:%M:%S")
        dur = f"{a['duration_ms'] / 1000:.1f}s" if a["duration_ms"] else "—"
        activity_rows += f"<tr><td>{ts}</td><td>{a['agent_name']}</td><td>{a['model']}</td><td>{dur}</td></tr>"
    if not activity_rows:
        activity_rows = "<tr><td colspan='4'>No activity yet</td></tr>"

    # System status
    import asyncio
    try:
        proc = await asyncio.create_subprocess_exec(
            "sh", "-c",
            "echo \"Uptime: $(uptime -p)\"; "
            "echo \"Load: $(cat /proc/loadavg | cut -d' ' -f1-3)\"; "
            "echo \"Disk: $(df -h / | tail -1 | awk '{print $3\"/\"$2\" (\"$5\")}')\"; "
            "echo \"RAM: $(free -h | awk '/Mem:/{print $3\"/\"$2}')\"",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=5)
        system_status = "<br>".join(stdout.decode().strip().split("\n"))
    except (subprocess.TimeoutExpired, OSError, asyncio.TimeoutError):
        system_status = '<span class="warn">Unable to get system info</span>'

    return HTML_TEMPLATE.format(
        system_status=system_status,
        usage_requests=summary["total_requests"],
        agents_table=agents_rows,
        tasks_table=tasks_rows,
        activity_table=activity_rows,
        updated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    )


async def health_check(db: Database) -> dict:
    """Run health checks and return status dict."""
    import asyncio
    import shutil

    checks: dict = {"status": "ok", "checks": {}}

    # DB check
    try:
        async with db.db.execute("SELECT 1") as cur:
            await cur.fetchone()
        checks["checks"]["database"] = "ok"
    except (RuntimeError, OSError) as e:
        checks["checks"]["database"] = f"error: {e}"
        checks["status"] = "degraded"

    # Engine check
    engine = get_settings().engine_binary
    import os
    if os.path.exists(engine) or shutil.which(engine):
        checks["checks"]["engine"] = "ok"
    else:
        checks["checks"]["engine"] = f"not found: {engine}"
        checks["status"] = "degraded"

    # Disk space
    try:
        import os
        stat = os.statvfs("/")
        free_gb = (stat.f_bavail * stat.f_frsize) / (1024 ** 3)
        checks["checks"]["disk_free_gb"] = round(free_gb, 1)
        if free_gb < 1:
            checks["status"] = "degraded"
    except OSError:
        pass

    # Activity
    try:
        tracker = UsageTracker(db)
        summary = await tracker.get_today_summary()
        checks["checks"]["requests_today"] = summary["total_requests"]
    except (RuntimeError, ValueError, OSError):
        pass

    checks["timestamp"] = time.time()
    return checks


async def start_dashboard(db: Database) -> None:
    """Start the dashboard web server with health check endpoint."""
    settings = get_settings()
    if not settings.dashboard_enabled:
        return

    from aiohttp import web

    async def handle_index(request: web.Request) -> web.Response:
        html = await render_dashboard(db)
        return web.Response(text=html, content_type="text/html")

    async def handle_health(request: web.Request) -> web.Response:
        import json as _json
        result = await health_check(db)
        status = 200 if result["status"] == "ok" else 503
        return web.Response(text=_json.dumps(result), content_type="application/json", status=status)

    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/health", handle_health)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.dashboard_port, reuse_address=True)
    _active_runner["instance"] = runner

    try:
        await site.start()
        logger.info("Dashboard on port %d", settings.dashboard_port)
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, OSError):
        pass
    finally:
        await runner.cleanup()
        _active_runner.pop("instance", None)


_active_runner: dict = {}


async def stop_dashboard() -> None:
    """Gracefully stop dashboard server."""
    runner = _active_runner.get("instance")
    if runner:
        await runner.cleanup()
        _active_runner.pop("instance", None)
