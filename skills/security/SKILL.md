---
name: security
description: Secrets, auth, OWASP, least privilege
audience: dev
---

## Security

Defense by default. Not paranoia, just professionalism.

### Secrets

- **Never hardcode** API keys, tokens, passwords in code.
- Environment variables for config, vault for sensitive secrets.
- `.env` always in `.gitignore`. Always.
- Rotate secrets after any incident, even suspected.
- Don't log secrets — sanitize before write.

### Authentication

- **Hash passwords** with `argon2` (or `bcrypt`). Never MD5/SHA1/plain.
- Use `secrets.token_urlsafe()` for tokens, never `random`.
- Sessions: HttpOnly + Secure + SameSite cookies.
- JWTs: short-lived access tokens + refresh tokens. Verify `exp` and `aud`.
- Rate limit auth endpoints to prevent brute force.

### OWASP top hits

- **SQL injection**: parameterized queries, never string concatenation
- **XSS**: escape output by default, sanitize HTML input
- **CSRF**: token per session, SameSite cookies
- **SSRF**: validate URLs before fetch, block private IP ranges
- **Path traversal**: never `open(user_input)`, always whitelist

### Least privilege

- Service users for daemons, not root
- File permissions: secrets are `chmod 600`, configs `644`
- Database users: separate read/write/admin accounts
- Containers: run as non-root, read-only filesystem when possible

### Secure defaults

- HTTPS only — redirect HTTP, set HSTS
- CSP headers to prevent XSS damage
- CORS: explicit allowlist, never `*` for credentialed requests
- Disable directory listing, server tokens, verbose errors in prod

### Don't

- Log full request bodies (might contain passwords)
- Email passwords or tokens (intercept-able)
- Trust input from any source — validate everything at boundaries
- Roll your own crypto. Use `cryptography`, `libsodium`, etc.
- Run prod with debug mode on
