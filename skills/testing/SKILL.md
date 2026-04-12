---
name: testing
description: Pyramid, contract testing, regression
audience: dev
---

## Testing

Tests as a discipline, not an afterthought.

### The pyramid

- **Many unit tests** — fast, isolated, run on every change
- **Some integration tests** — DB, external services, slower
- **Few end-to-end tests** — full flow, slowest, brittle
- Inverted pyramid (mostly e2e) means slow CI and brittle suite.

### Test the contract, not the implementation

- Test what the function PROMISES (input → output, side effects).
- Don't test internal details — they change during refactoring.
- If a refactor breaks a test but the behavior is the same, the test was bad.

### Mock vs real

- **External APIs**: mock (don't depend on third-party in tests)
- **Your own database**: use a real test DB, not mocks (mocks lie about migrations)
- **File system**: use `tmp_path` fixtures
- **Time**: freeze with `freezegun` if logic depends on it

### Coverage is a metric, not a goal

- 100% coverage doesn't mean bug-free
- 60% covering the right things > 95% covering trivial getters
- Focus on: branches, error paths, boundary conditions

### Regression tests

- **Always** add a test for every bug fix
- The test should fail BEFORE your fix, pass AFTER
- This prevents the bug from coming back

### Test naming

- `test_<what>_<condition>_<expected>`
- Example: `test_login_with_wrong_password_returns_401`
- Bad: `test_1`, `test_login`, `test_user`

### Don't

- Tests that pass without assertions
- `time.sleep()` based tests (use proper waits/mocks)
- Tests that depend on test order
- Skip tests "temporarily" — fix or delete
- Test private methods directly — test through public interface
