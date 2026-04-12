---
name: code-review
description: Review like a senior, not a nitpicker
audience: dev
---

## Code review

Review code like a senior. Not nitpicking, not rubber-stamping.

### What to look for

**High value:**
- Bugs and logic errors
- Security issues (injection, secrets, auth bypass)
- Edge cases (null, empty, race conditions, boundary)
- Error handling (or lack of it)
- Performance issues that matter (N+1 queries, infinite loops)
- Breaking changes for callers

**Low value (don't waste time):**
- Style preferences your linter could catch
- "I would have done it differently"
- Renaming variables
- Adding/removing whitespace

### Be specific

- Bad: "This is wrong"
- Good: "Line 42 — this throws KeyError if `data` is empty. Add `data.get('key', default)` or check first"

- Bad: "Add error handling"
- Good: "Line 87 — if the API returns 429, this loops forever. Add exponential backoff with max retries"

### Suggest, don't dictate

- "Have you considered X?" over "Use X"
- Show alternative code in suggestion blocks
- Explain WHY, not just what

### Praise good patterns

- If you only point out negatives, reviews feel demoralizing
- Notice clean abstractions, good test coverage, smart trade-offs
- "Nice — this handles the edge case I missed in #123"

### Review etiquette

- Respond within 24h or hand off
- Approve when ready, request changes when needed, comment for discussion
- Don't block on personal preferences — only on real issues
- If you disagree strongly, hop on a call instead of comment war

### Self-review first

Before requesting review, **review your own diff**:
- Read every line as if you didn't write it
- Run the tests
- Check for `console.log`, `print`, debug code
- Verify the diff is minimal and on-topic

### Don't

- Approve without reading
- Block PRs because of style preferences
- Make the author feel stupid
- Demand changes via "we should..." (write the code if you care)
- Pile on after someone else already reviewed
