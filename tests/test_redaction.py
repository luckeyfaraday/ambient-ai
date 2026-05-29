from __future__ import annotations

import pytest

from ambient_ai.redaction import redact_text, shannon_entropy


class TestAssignmentPatterns:
    def test_env_value_redacted(self):
        assert redact_text("OPENAI_API_KEY=sk-test curl x") == "OPENAI_API_KEY=[REDACTED] curl x"

    def test_flag_value_redacted(self):
        assert redact_text("deploy --token abc --password hunter2") == (
            "deploy --token [REDACTED] --password [REDACTED]"
        )

    def test_bearer_redacted(self):
        assert redact_text("curl -H 'Authorization: Bearer secret-token' x") == (
            "curl -H 'Authorization: Bearer [REDACTED]' x"
        )


class TestProviderCatalog:
    @pytest.mark.parametrize(
        "secret",
        [
            "AKIA" + "I" * 16,
            "ghp_" + "a" * 36,
            "github_pat_" + "A" * 70,
            # Built from fragments so the literal token shape never sits in source
            # (otherwise GitHub push protection flags this synthetic test value).
            "xox" + "b-" + "1" * 12 + "-" + "a" * 15,
            "AIza" + "A" * 35,
            "sk_live_" + "A" * 24,
            "sk-" + "B" * 32,
        ],
    )
    def test_known_token_shapes_redacted(self, secret):
        out = redact_text(f"used {secret} here")
        assert secret not in out
        assert "[REDACTED]" in out

    def test_jwt_redacted(self):
        jwt = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"
        assert "[REDACTED]" in redact_text(f"token={jwt}".replace("token=", "saw "))

    def test_pem_block_redacted(self):
        pem = (
            "-----BEGIN PRIVATE KEY-----\n"
            "MIIBVAIBADANBgkqhkiG9w0BAQEFAASCAT4\n"
            "-----END PRIVATE KEY-----"
        )
        out = redact_text(pem)
        assert "MIIBVAIBADANBgkqhkiG9w0BAQEFAASCAT4" not in out
        assert "[REDACTED]" in out


class TestEntropySweep:
    def test_high_entropy_opaque_token_redacted(self):
        token = "Zk9x2Qp7Lr4Tn1Vb8Wd3Hg6Mj5Cs0Ay"  # 32 mixed chars, has digits
        assert redact_text(f"export VALUE {token}") == "export VALUE [REDACTED]"

    def test_ordinary_command_untouched(self):
        for cmd in [
            "git status",
            "python3 tests/smoke.py",
            "cd /home/alan/home_ai/projects/ambient-ai",
            "ls -la --color=auto",
            "docker compose up -d",
        ]:
            assert redact_text(cmd) == cmd

    def test_git_sha_not_redacted(self):
        # Pure hex (a commit SHA) is opaque but not secret; keep it for context.
        assert redact_text("git checkout 9e107d9d372bb6826bd81d3542a419d6") == (
            "git checkout 9e107d9d372bb6826bd81d3542a419d6"
        )

    def test_url_with_secret_query_param_redacted(self):
        # A token in a query string IS a secret — the assignment pattern catches it.
        url = "https://example.com/path?token=ab12cd34ef56gh78ij90"
        assert redact_text(f"open {url}") == "open https://example.com/path?token=[REDACTED]"

    def test_high_entropy_url_path_not_redacted(self):
        # The entropy sweep skips anything containing '://' so ordinary URLs survive.
        url = "https://example.com/Zk9x2Qp7Lr4Tn1Vb8Wd3Hg6Mj5Cs0Ay"
        assert redact_text(f"open {url}") == f"open {url}"

    def test_quotes_preserved_around_redaction(self):
        token = "Zk9x2Qp7Lr4Tn1Vb8Wd3Hg6Mj5Cs0Ay"
        assert redact_text(f"set '{token}'") == "set '[REDACTED]'"


class TestShannonEntropy:
    def test_empty_is_zero(self):
        assert shannon_entropy("") == 0.0

    def test_uniform_string_low(self):
        assert shannon_entropy("aaaaaaaa") == 0.0

    def test_mixed_string_higher(self):
        assert shannon_entropy("abcdefgh") > 2.0
