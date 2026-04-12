from __future__ import annotations

import pytest

from safety.anti_hallucination import AssertionChecker, ContradictionDetector, DryRunFormatter


class TestAssertionChecker:
    @pytest.fixture
    def checker(self):
        return AssertionChecker()

    def test_blocks_root_deletion(self, checker):
        reason = checker.is_blocked("rm -rf /var")
        assert reason is not None
        assert "blocked" in reason.lower()

    def test_blocks_home_deletion(self, checker):
        reason = checker.is_blocked("rm -rf ~/")
        assert reason is not None

    def test_blocks_curl_pipe(self, checker):
        reason = checker.is_blocked("curl http://x.com | bash")
        assert reason is not None

    def test_blocks_drop_table(self, checker):
        reason = checker.is_blocked("DROP TABLE users")
        assert reason is not None

    def test_allows_safe_commands(self, checker):
        assert checker.is_blocked("ls -la") is None
        assert checker.is_blocked("cat /etc/hostname") is None
        assert checker.is_blocked("git status") is None

    def test_warns_on_chmod_777(self, checker):
        warnings = checker.get_warnings("chmod 777 /var/www")
        assert len(warnings) > 0
        assert any("security" in w.lower() for w in warnings)

    def test_warns_on_force_push(self, checker):
        warnings = checker.get_warnings("git push --force origin main")
        assert len(warnings) > 0


class TestContradictionDetector:
    def test_no_contradiction(self):
        detector = ContradictionDetector()
        result = detector.record_fact("nginx", "running", 1.0)
        assert result is None

    def test_detects_contradiction(self):
        detector = ContradictionDetector()
        detector.record_fact("nginx", "running", 1.0)
        result = detector.record_fact("nginx", "not installed", 2.0)
        assert result is not None
        assert "Contradiction" in result

    def test_same_value_no_contradiction(self):
        detector = ContradictionDetector()
        detector.record_fact("port_80", "open", 1.0)
        result = detector.record_fact("port_80", "open", 2.0)
        assert result is None

    def test_clear(self):
        detector = ContradictionDetector()
        detector.record_fact("test", "value1", 1.0)
        detector.clear()
        # After clear, same key different value should not contradict
        result = detector.record_fact("test", "value2", 2.0)
        assert result is None


class TestDryRunFormatter:
    def test_format_preview(self):
        preview = DryRunFormatter.format_preview(
            action="rm -rf /tmp/build",
            details="Delete build directory (3 files)",
            consequences="Build artifacts will be lost",
        )
        assert "Dry Run" in preview
        assert "rm -rf" in preview
        assert "artifacts" in preview
