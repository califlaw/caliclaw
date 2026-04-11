---
name: incident-response
description: Production fires playbook
audience: devops
---

## Incident response

When production breaks at 3 AM. Don't panic — follow the playbook.

### Triage (first 5 minutes)

1. **Severity**: How bad is it?
   - SEV1: Total outage, data loss
   - SEV2: Major feature broken, many users affected
   - SEV3: Minor issue, workaround exists
2. **Impact**: How many users? Which features? Region-specific?
3. **Blast radius**: Will it spread? Cascade to other services?

### Communicate first, fix second

- **Acknowledge**: "We're aware, investigating" within 5 min
- Update every 15-30 min even if no progress
- Status page > Slack > email > silence
- Users hate silence more than bugs

### Stabilize before fixing

- **Rollback over heroic fix** — revert the deploy first, debug second
- Take the broken thing offline if it's actively damaging
- Stop the bleeding, then operate
- Heroic 3am fixes cause new outages 80% of the time

### Investigation

- **Recent changes first**: deploys, config changes, feature flags in last 24h
- **Read logs systematically**: errors, warnings, anomalies
- **Check dependencies**: is your DB ok? Cache? Third-party APIs?
- **Reproduce in staging** if possible (don't test fixes in prod)

### Fix and verify

- Smallest possible fix that resolves the issue
- Test in staging first, even at 3 AM
- Deploy with extra monitoring
- Watch for 30 min before declaring "fixed"

### Postmortem (after the fire is out)

- Within 48 hours, write a postmortem doc
- **Blameless** — focus on system failures, not people
- Sections: timeline, impact, root cause, what worked, what didn't, action items
- Action items get tracked and closed

### Don't

- Skip the postmortem because "we're busy"
- Blame individuals — humans don't cause outages, broken systems do
- "Quick fix" without rollback plan
- Hide the incident from users
- Let alerts go unacknowledged
