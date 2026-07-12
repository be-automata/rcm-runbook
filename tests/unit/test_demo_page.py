"""Demo chat page: serves HTML publicly, carries no secret, wires the run endpoint."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(scope="module")
def client() -> TestClient:
    from rcm_runbook import app as app_module

    return TestClient(app_module.app)


class TestDemoPage:
    def test_served_without_key(self, client):
        # The HTML page is public; auth happens on its API calls, not the page load.
        resp = client.get("/demo")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")

    def test_page_holds_no_secret(self, client):
        body = client.get("/demo").text
        assert "OSK_" not in body
        assert "sk-ant" not in body
        # It reads the key from the URL at runtime instead
        assert "URLSearchParams" in body
        assert "/agents/facilitador-rcm/runs" in body

    def test_run_endpoint_is_gated(self, client):
        from rcm_runbook.config import settings

        if not settings.os_security_key:
            pytest.skip("no security key configured in this environment")
        # The page's target endpoint must reject calls without the key
        resp = client.post(
            "/agents/facilitador-rcm/runs",
            data={"message": "hola", "stream": "false"},
        )
        assert resp.status_code == 401
