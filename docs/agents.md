# Agents

## Overview

Agents are isolated Claude instances with their own personality (soul), skills, and permissions. The main agent coordinates everything and can spawn new agents on-the-fly.

## Scopes

### Global (`agents/global/`)
Permanent agents available across all projects. The `main` agent is always global.

### Project (`agents/projects/<project>/`)
Tied to a specific project. Know the codebase, its quirks, how to test it. Survive across sessions but only activate when working on that project.

### Ephemeral (`agents/ephemeral/`)
Created for one task, killed after. Main agent decides when to spawn them. Knowledge is extracted before deletion and saved to memory.

## Soul files

Each agent has a directory with `.md` files that define its behavior:

```
agents/global/main/
├── SOUL.md       What the agent is, how it thinks, rules to follow
├── IDENTITY.md   Name, role, communication style
├── USER.md       What the agent knows about you
└── TOOLS.md      Available tools and how to use them
```

Only `SOUL.md` is required. Others are optional.

## Lifecycle

```
spawn → active → [run tasks] → kill (with knowledge extraction)
                             → promote (ephemeral → project or global)
                             → pause
```

### Spawning

Main agent creates new agents when it needs specialization or parallelism:

```
/spawn researcher Finds information and writes summaries
/spawn devops Manages servers, deploys apps, monitors health
```

Or the main agent spawns them autonomously during complex tasks.

### Killing

```
/kill researcher
```

Before killing, caliclaw extracts what the agent learned and saves it to memory. The agent dies but its knowledge lives on.

### Promoting

```
/promote researcher global
/promote backend-dev project
```

Moves an ephemeral agent to a permanent scope.

## Running agents

### Single run
Agent processes one prompt and returns.

### Loop
Agent works autonomously in a loop until the task is complete:
```
/loop Build a REST API for user management with tests
```
Reports progress every N iterations. Stops at max iterations, max time, or max usage.

### Swarm
Multiple agents work in parallel:
```
Main spawns: researcher, coder, reviewer
  → researcher gathers info
  → coder writes code (waits for researcher)
  → reviewer checks code (waits for coder)
```

### Pipeline
Sequential chain where each agent's output feeds the next:
```
research → plan → code → review → test → deploy
```

## Permissions

Each agent can have restricted tool access:

```yaml
# In agent's permissions
allowed_tools: [Read, Write, Edit, Bash]
denied_tools: [vault, ssh]
```

Main agent has full access. Ephemeral agents are restricted by default.
