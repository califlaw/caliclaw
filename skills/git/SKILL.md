---
name: git
description: Atomic commits, branch hygiene, recovery
audience: dev
---

## Git

Version control like a senior. Not just `git commit -m "fix"`.

### Commits

- **Atomic**: one logical change per commit. If you can't describe it in one sentence, split it.
- **Message format**: WHY in the first line, WHAT in the body if needed.
- Bad: `"fix bug"`, `"updates"`, `"wip"`
- Good: `"fix race condition in queue when two enqueues collide"`
- First line ≤72 chars. Imperative mood: "Add X" not "Added X".

### Branch hygiene

- `main` is sacred. Never push directly. Always PR.
- Branch names: `feature/short-name`, `fix/issue-123`, `chore/update-deps`
- Delete branches after merge. `git branch -d <name>`.
- Rebase your feature branch onto main before opening PR.

### Recovery

- **Lost commits**: `git reflog` shows everything. You can almost always recover.
- **Bad commit**: `git revert <sha>` (safe, preserves history) over `git reset --hard` (destructive)
- **Wrong branch**: `git stash`, switch, `git stash pop`
- **Half-staged mess**: `git reset --keep` (keeps working changes)

### Investigate before you change

- `git log --oneline <file>` — history of a file
- `git blame <file>` — who wrote each line and when
- `git log -S "search"` — find when a string was added/removed
- `git show <sha>` — see what a commit changed

### Never

- `git push --force` to shared branches (use `--force-with-lease` if you must)
- `git rebase` published commits
- Commit secrets, large binaries, generated files
- Use `git add .` blindly — review with `git status` first

### Conflict resolution

- Read both sides before accepting either. Conflicts often hide bugs.
- After resolving: run tests before committing the merge.
- For complex merges: `git mergetool` over manual editing.
