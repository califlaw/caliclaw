# Memory

## How it works

Memory is stored as `.md` files in `memory/` with a frontmatter header:

```markdown
---
name: User prefers dark mode
description: UI preference learned during setup
type: user
---

User mentioned they always use dark themes. Apply dark mode defaults when creating UIs.
```

`MEMORY.md` is the index — a list of links to all memory files. Agents read this first to know what's available.

## Memory types

### user
What caliclaw knows about you. Updated automatically by the dreaming engine.

### project
Context about current work, decisions, deadlines.

### feedback
How you want caliclaw to behave. Corrections and confirmations.

### reference
Pointers to external resources (URLs, tools, dashboards).

## How agents use memory

1. Before each run, relevant memory is loaded into the system prompt
2. Agents can write new memories during their work
3. The dreaming engine consolidates memory overnight
4. Stale memory is detected and updated

## Dreaming

Every night at 3:00 AM, caliclaw reviews the day's conversations:
- Extracts key facts about the user
- Identifies recurring patterns
- Updates USER.md
- Archives old conversations

This runs on haiku to save tokens.

## CLI

```bash
caliclaw memory list          # All entries
caliclaw memory show          # Show index
caliclaw memory search docker # Search
caliclaw memory clear         # Delete all (asks confirmation)
```
