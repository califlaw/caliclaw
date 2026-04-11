---
name: shell
description: Bash mastery, pipes, processes, system tools
audience: dev
---

## Shell

Senior-level command line. Composable one-liners over multi-line scripts.

### Tools you should know

- **Find**: `find . -name "*.py" -newer /tmp/marker -print0 | xargs -0`
- **Grep variants**: `grep -rn`, `rg`, `ag` — know which is fastest
- **Text processing**: `awk '{print $2}'`, `sed -i 's/old/new/g'`, `cut`, `tr`
- **JSON**: `jq '.field'`, `jq -r '.[] | .name'`
- **Process**: `ps aux`, `pgrep -af`, `lsof -i :8080`, `fuser 8080/tcp`
- **Disk**: `du -sh *`, `df -h`, `ncdu`
- **Net**: `ss -tlnp`, `curl -v`, `dig +short`

### Rules

- **Always quote paths**: `"$file"` — protects against spaces
- **Check before destruction**: `ls foo/` before `rm -rf foo/`
- **Use `--` separator** when args might start with `-`: `rm -- "$file"`
- **`set -euo pipefail`** at top of every bash script
- **Trap signals**: `trap cleanup EXIT` for temp files

### Composition over scripts

```bash
# Bad: 50-line bash script
# Good: one pipeline
find /var/log -name "*.log" -mtime +30 -print0 | xargs -0 rm -v
```

### Process control

- `kill -TERM` first, `kill -9` only as last resort
- `nohup cmd &` for detached background
- `disown` to remove from shell job control
- `flock` for file-based locking between processes

### Don't

- `curl ... | sh` — pipe to shell is dangerous
- `chmod 777` — almost always wrong
- `sudo` in scripts — make it explicit at invocation
- Hardcoded `/tmp/file` — use `mktemp`
