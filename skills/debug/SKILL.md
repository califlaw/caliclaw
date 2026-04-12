---
name: debug
description: Read errors word-by-word, isolate, verify
audience: dev
---

## Debug

Root-cause analysis like a senior. Not "try fixes randomly".

### Read the error message

- Read the **entire** error, not just the first line.
- Note line numbers, file paths, and the call stack.
- The error message is usually telling you exactly what's wrong. Trust it first.
- If it doesn't make sense — the message is wrong, OR you're looking at the wrong code.

### Reproduce, then fix

- **First step**: reproduce reliably. If you can't reproduce, you can't fix.
- Minimal repro: smallest code/data/steps that triggers the bug.
- If the bug is intermittent — write down ALL the conditions when it appears.

### Hypothesis-driven

1. State the bug in one sentence
2. Form a hypothesis: "I think X causes Y because Z"
3. Design a test that proves or disproves it
4. Run the test
5. Update hypothesis based on result

If you're not testing hypotheses, you're guessing.

### Symptom vs root cause

- **Symptom**: "the page returns 500"
- **Cause**: "database connection pool exhausted under load"
- Fix the cause, not the symptom. Adding `try/except` around a 500 hides the bug, doesn't fix it.

### When stuck

- **Binary search the failure**: `git bisect` for regressions, comment-out half the code, etc.
- **Add logging strategically** — at every state transition
- **Read the source** of the library you're using. Usually it's clearer than docs.
- **Take a break** — fresh eyes solve in 5 min what tired eyes can't in 5 hours.

### Tools

- `pdb` / `ipdb` — Python debugger, breakpoints
- `strace -e trace=network` — see syscalls
- Browser DevTools Network/Console for web bugs
- `tcpdump` / `wireshark` for protocol-level mysteries

### Don't

- Try random fixes "to see what works"
- Skip reading the error
- Assume the bug is in someone else's code
- Fix the symptom and move on
- Believe "it works on my machine" without checking why
