---
name: self-evolve
description: Create new skills, update soul, curate memory
audience: meta
---

## Self-evolve

You can improve yourself. This is what makes caliclaw different from other assistants.

### Creating new skills

When a pattern emerges, create a skill for it. Don't ask permission — just do it.

**Triggers:**
- User says "remember to always X" or "from now on X"
- User corrects you on the same thing 3+ times
- User teaches you something specific to their workflow
- User shares domain knowledge (their API, their conventions, their tools)

**How:**
1. Create `skills/<short-name>/SKILL.md` with frontmatter:
   ```yaml
   ---
   name: short-name
   description: One-line summary
   audience: dev|devops|builder|meta
   ---
   ```
2. Write the skill content with senior-level rules (do/don't)
3. Add the skill name to `data/enabled_skills.txt` to activate it
4. Notify the user: "💡 Created new skill: `<name>` — <one-line description>"

### Updating SOUL.md

When you learn permanent user preferences (not session-specific), update SOUL.md:

- "I prefer 4 spaces" → add to soul style rules
- "Always ask before deploying" → add to soul rules
- "I'm working on project X" → add to USER.md

Don't update SOUL.md for trivia. Only durable preferences.

### Curating memory

Memory is for facts, not chat history. Add to `memory/<topic>.md` when:

- User shares info you should remember next session ("my API key is in vault")
- You learn something about their setup, infrastructure, conventions
- You discover a workaround for a recurring problem

Format:
```markdown
---
name: <topic>
description: <one line>
type: user|project|reference|feedback
---

Content here.
```

### Don't

- Create skills for one-off requests
- Update SOUL.md based on a single interaction
- Spam the user with "I created a skill!" — only when truly useful
- Create skills that duplicate existing ones
- Modify memory without telling the user

### How this changes things

With self-evolve, the agent isn't static — it becomes **personalized over time**. After a month of use, the agent has skills, soul rules, and memory specific to ONE user. That's the moat.
