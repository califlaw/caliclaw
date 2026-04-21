---
name: obsidian
description: Read from and write to the user's Obsidian vault. Use when the user asks you to save research, take notes, log what you did, or look up something that might already be in their notes.
---

# Obsidian Vault Integration

You can read from and write to the user's Obsidian vault. Treat it as
their personal knowledge base — you're a contributor, not the owner.

## When to use this skill

- User asks to save, file, log, journal, or "write it down"
- User asks about something they "wrote about earlier" or "have notes on"
- You just finished research / analysis and the result is worth keeping
- User asks for their daily note or wants to add to it

## When NOT to use this skill

- Ephemeral chat replies (no value in persisting)
- Something better placed in caliclaw's own `memory/` (preferences about
  the user as a user, agent learnings, operational facts) — that's
  caliclaw's internal memory, separate from the user's Obsidian vault
- When the vault isn't configured (`intelligence.obsidian.is_configured()`
  returns False) — tell the user how to set `OBSIDIAN_VAULT_PATH` and stop

## API

```python
from intelligence import obsidian

obsidian.is_configured()            # True/False — always check first
obsidian.vault_path()                # Path | None

# Write a standalone note (goes to Inbox/caliclaw/ by default)
obsidian.write_note(
    title="Z-Image v9 findings",
    body="...markdown body...",
    tags=["research", "ai-farm"],
    links=["Sofia Persona", "AI Farm Pipeline"],  # [[wikilinks]]
    subdir="Research",  # optional, otherwise inbox
)

# Append a timestamped section to today's daily note
obsidian.append_to_daily(
    section="Caliclaw heartbeat",
    body="- Services green\n- 3 agents idle\n- VPS uptime 14d",
)

# Search existing notes (rg under the hood)
hits = obsidian.search("sofia persona", max_hits=5)
# [{"path": "Personas/Sofia.md", "line_no": 12, "preview": "..."}]

# List most-recently-edited notes
obsidian.list_recent(limit=10)
```

## Formatting conventions

- Files are markdown with Obsidian-compatible frontmatter: `source`,
  `created`, `tags`
- Use `[[Wikilinks]]` for cross-references — Obsidian's graph picks
  them up automatically
- Tags can be YAML list (frontmatter) or `#inline-tags` in the body
- Daily notes live at `<vault>/Daily/YYYY-MM-DD.md` by default
- New notes from caliclaw land in `<vault>/Inbox/caliclaw/` unless you
  pass `subdir="…"`

## Worked examples

**Research result:**
```python
obsidian.write_note(
    title="Competitor analysis: IvyVale",
    body=full_research_markdown,
    tags=["competitors", "research"],
    subdir="Research/Competitors",
    links=["AI Farm Strategy"],
)
```

**Daily log of ops activity:**
```python
obsidian.append_to_daily(
    section="VPS maintenance",
    body="Upgraded CUDA toolkit 12.4 → 12.6. All workers restarted cleanly.",
)
```

**Recall something the user wrote:**
```python
hits = obsidian.search("z-image turbo", max_hits=5)
if hits:
    note = Path(obsidian.vault_path()) / hits[0]["path"]
    content = note.read_text(encoding="utf-8")
    # ...use as context
```

## Safety

- **Never delete** notes. Only create, append, or read.
- **Don't overwrite** existing notes silently — `write_note` creates a
  file named after the title; if a collision matters, check first with
  `search()` or `(vault / "Inbox/caliclaw" / f"{title}.md").exists()`.
- The vault belongs to the user. If in doubt about whether to write,
  ask.
