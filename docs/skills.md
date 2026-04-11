# Skills

## What are skills

Skills are reusable instruction sets that agents can load. Each skill is a directory with a `SKILL.md` file.

## Structure

```
skills/
├── deploy/
│   └── SKILL.md
├── code-review/
│   └── SKILL.md
└── server-admin/
    └── SKILL.md
```

## SKILL.md format

```markdown
---
name: deploy
description: Deploy applications to production
requires: [docker, ssh]
tools: [Bash, Read, Write]
---

## Instructions

When asked to deploy:

1. Run tests first (`pytest` or `npm test`)
2. Check git status — no uncommitted changes
3. Build docker image
4. Push to registry
5. SSH to server and pull new image
6. Restart container
7. Verify health endpoint responds
8. Report success or rollback

## Rollback procedure

If health check fails:
1. Stop new container
2. Start previous version
3. Report failure with logs
```

## How skills are loaded

1. Global skills from `skills/` are available to all agents
2. Skills listed in an agent's config are injected into its system prompt
3. Agents can reference skills by name in conversation

## Creating skills

Agents can create new skills themselves after learning a recurring task. You can also create them manually:

```bash
mkdir -p skills/my-skill
cat > skills/my-skill/SKILL.md << 'EOF'
---
name: my-skill
description: What this skill does
---

Instructions here...
EOF
```

View available skills: `/skills` in Telegram or `caliclaw` CLI.
