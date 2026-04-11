# Heartbeats & Scheduling

## Default heartbeats

Created automatically on `caliclaw init`:

### quick_pulse (every 5 min)
Checks CPU, RAM, disk. Only alerts if something is critical. Uses haiku.

### system_review (every 30 min)
Checks Docker containers, recent errors in logs, SSL certificates, disk trends. Uses haiku.

### morning_brief (every day at 9:00)
Summary: overnight events, system status, resource usage, active tasks. Sent to Telegram. Uses sonnet.

### nightly_dream (every day at 3:00)
Memory consolidation: reviews conversations, extracts insights, updates USER.md. Silent. Uses sonnet.

## Custom tasks

### Via Telegram
```
/schedule */30 * * * * Check nginx error log for 5xx errors
/schedule 0 18 * * * Daily backup report
```

### Schedule types
- `cron`: standard cron expression (`*/5 * * * *`)
- `interval`: seconds between runs (`3600` = every hour)
- `once`: run once and complete

### Management
```
/tasks          List all tasks
/pause 3        Pause task #3
/resume 3       Resume task #3
```

## Token budget

Heartbeats have a daily budget (default 10% of usage limit):
- quick_pulse: ~0.05% each (haiku)
- system_review: ~0.05% each (haiku)
- morning_brief: ~0.2% (sonnet)
- nightly_dream: ~0.2% (sonnet)

Total: ~5-8% per day on heartbeats.

## Model routing

Tasks are automatically routed to the cheapest suitable model:

| Task | Model |
|------|-------|
| Heartbeat checks | haiku |
| Simple lookups | haiku |
| General work | sonnet |
| Code review | sonnet |
| Architecture decisions | opus |

At high usage (>80%), all tasks downgrade: opus→sonnet, sonnet→haiku.
At 95%, everything stops except critical heartbeats.
