---
name: research
description: Authoritative sources, verify currency, cite
audience: dev
---

## Research

Find answers like a senior. Not just "google and copy first result".

### Source hierarchy

Trust in this order:
1. **Official docs** — `docs.python.org`, `pkg.go.dev`, library README
2. **Source code** — when docs are wrong or missing
3. **Maintainers' blogs** — written by the people who built it
4. **Stack Overflow** — only highly-voted answers, check the date
5. **Random blogs** — last resort, verify everything

### Verify currency

- **Date matters**. A 2019 answer might be wrong in 2026.
- Check the language version, framework version, OS version.
- "It worked in 0.x" doesn't mean it works in 1.x.

### Cite your sources

- When you use info from the web, include the URL.
- Format: `(source: https://example.com/page)`
- This lets the user verify and helps the next time too.

### Search techniques

- Use exact error messages in quotes
- Add language/framework name: `"FooError" python 3.12`
- Search GitHub issues, not just web: `site:github.com FooError`
- For libraries: search the source code for the symbol you're stuck on

### Synthesize, don't dump

- Don't paste 5 links and call it research
- Read them, extract the relevant facts, write a clear summary
- If sources disagree, mention both and explain the trade-off

### Don't

- Trust outdated tutorials
- Copy code from random blogs without understanding
- Skip the official docs because they're "boring"
- Confuse popular with correct
