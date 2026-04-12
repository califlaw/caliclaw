---
name: code
description: Read first, minimal diffs, no half-finished work
audience: dev
---

## Code

Senior-level rules for reading, writing, and modifying code.

### Read before write

- Always read existing code before changing it. Existing code is the source of truth.
- Match the project's existing style — naming, indentation, patterns.
- If the project uses 4 spaces, you use 4 spaces. Don't impose your preferences.

### Minimal diffs

- Fix exactly what was asked, nothing more.
- If asked to fix bug X, fix bug X — don't refactor module Y because you don't like it.
- No drive-by improvements unless explicitly requested.
- Smaller diffs = easier review = less risk.

### No half-finished work

- Don't leave `TODO` comments unless explicit.
- Don't write code that "works for the happy path" — handle the obvious edge cases.
- Don't add error handling for impossible scenarios. Trust internal contracts.
- If you can't finish, say so explicitly. Don't pretend.

### Naming

- Names should explain WHY, not WHAT (`retry_count` not `i`).
- Avoid generic names: `data`, `info`, `helper`, `utils`.
- Boolean names start with `is_`, `has_`, `can_`, `should_`.

### Comments

- Default to NO comments. Good names beat comments.
- Comment only when WHY is non-obvious — hidden constraints, surprising behavior.
- Never comment WHAT the code does.

### Don't

- Reformat unrelated lines
- Rename things "to be more consistent"
- Add abstractions for hypothetical future requirements
- Use `TODO`/`FIXME` as a way to ship incomplete work
