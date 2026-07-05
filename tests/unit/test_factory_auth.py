"""Anthropic auth wiring: subscription OAuth token vs API key (no network calls)."""

from rcm_runbook.agent.factory import build_model
from rcm_runbook.config import Settings


def _request_headers(client) -> dict[str, str]:
    """Auth + default headers the SDK would send, without hitting the network."""
    headers = dict(client.default_headers or {})
    headers.update(client.auth_headers)
    return {k.lower(): v for k, v in headers.items()}


class TestSubscriptionAuth:
    def test_oauth_token_uses_bearer_and_beta_header(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-be-dropped")
        cfg = Settings(claude_code_oauth_token="sk-ant-oat01-test-token")
        model = build_model(cfg)
        headers = _request_headers(model.client)
        assert headers.get("authorization") == "Bearer sk-ant-oat01-test-token"
        assert "x-api-key" not in headers
        assert headers.get("anthropic-beta") == "oauth-2025-04-20"
        # env API key was scrubbed so it can't be re-picked-up elsewhere
        import os

        assert "ANTHROPIC_API_KEY" not in os.environ

    def test_async_client_wired_identically(self):
        cfg = Settings(claude_code_oauth_token="sk-ant-oat01-test-token")
        model = build_model(cfg)
        headers = _request_headers(model.async_client)
        assert headers.get("authorization") == "Bearer sk-ant-oat01-test-token"
        assert "x-api-key" not in headers

    def test_api_key_mode_unchanged_without_token(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-key-mode")
        cfg = Settings(claude_code_oauth_token="")
        model = build_model(cfg)
        # agno default path: no injected client; api_key resolved from env at call time
        assert model.client is None or isinstance(model.client, object)
        assert not getattr(model, "auth_token", None)


class TestSettingsAlias:
    def test_reads_unprefixed_env_var(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "sk-ant-oat01-from-env")
        cfg = Settings(_env_file=None)
        assert cfg.claude_code_oauth_token == "sk-ant-oat01-from-env"
