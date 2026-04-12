---
name: browser
description: Web automation — login, forms, scrape, screenshots
audience: builder
---

## Browser

Web automation via Playwright. Beyond just reading pages.

### When to use

- **Login flows** — sites that need credentials
- **Form automation** — fill, submit, multi-step wizards
- **JS-rendered content** — SPAs where WebFetch returns empty HTML
- **Screenshots** — visual verification, reports, monitoring
- **Web testing** — verify your own deployed sites
- **Scraping** — when there's no API and you have permission

### When NOT to use

- Simple page reading → use `WebFetch` (faster, no Chromium overhead)
- Search → use `WebSearch`
- API calls → use `curl` / `requests`
- Authenticated APIs → use proper API clients with tokens

### How

```python
from playwright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch(headless=True)
    page = await browser.new_page()

    await page.goto("https://example.com")
    await page.fill("input[name='email']", "user@example.com")
    await page.fill("input[name='password']", os.environ["MY_PASSWORD"])
    await page.click("button[type='submit']")
    await page.wait_for_url("**/dashboard")

    text = await page.text_content("div.result")
    await page.screenshot(path="result.png")

    await browser.close()
```

### Rules

- **Always headless=True** unless debugging
- **Reasonable timeouts** — 30s max for actions, 60s for navigation
- **Close the browser** in `finally` or context manager
- **Never hardcode credentials** — env vars or vault only
- **Take screenshots** before/after critical actions for audit trail
- **Respect robots.txt** when scraping
- **Rate limit** your requests — don't hammer servers
- **User-Agent** — set a real one, don't pretend you're not a bot

### Setup

Skill requires Playwright. Install once:
```bash
pip install playwright
playwright install chromium
```

This is a heavy dependency (~300MB), but the capability is worth it.

### Don't

- Run with `headless=False` in production (memory leak risk)
- Skip `wait_for_*` and rely on `sleep()` (brittle)
- Store cookies/sessions in code (use `context.storage_state`)
- Scrape sites that explicitly forbid it (ToS / `robots.txt`)
- Use Browser when a simple HTTP request would do
