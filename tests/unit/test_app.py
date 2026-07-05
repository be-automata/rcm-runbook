"""AgentOS app construction + export download endpoint (P3b exit criteria)."""


import pytest
from fastapi.testclient import TestClient

from rcm_runbook.config import settings
from rcm_runbook.export.excel import export_xlsx
from tests.unit.test_compliance import full_session


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    exports = tmp_path_factory.mktemp("exports")
    settings.exports_dir = str(exports)
    settings.db_path = str(tmp_path_factory.mktemp("db") / "test.db")
    from rcm_runbook import app as app_module

    app_module.settings.exports_dir = str(exports)
    return TestClient(app_module.app)


class TestApp:
    def test_agentos_routes_mounted(self, client):
        # AgentOS exposes an OpenAPI schema with its runtime endpoints
        schema = client.get("/openapi.json").json()
        paths = list(schema["paths"])
        assert any("agent" in p or "run" in p or "session" in p for p in paths), paths

    def test_download_serves_golden_export(self, client):
        path = export_xlsx(full_session(), settings.exports_dir, session_id="any-session")
        resp = client.get(f"/exports/any-session/{path.name}")
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )
        assert len(resp.content) > 5000

    def test_download_rejects_traversal(self, client):
        assert client.get("/exports/s/..%2F..%2Fetc%2Fpasswd").status_code in (400, 404)
        assert client.get("/exports/s/no-existe.xlsx").status_code == 404
        assert client.get("/exports/s/archivo.txt").status_code == 400


class TestResumeAfterRestart:
    def test_session_state_survives_rebuild(self):
        """Round-trip through the serialization boundary (what AgentOS persists)."""
        from rcm_runbook.models.session import RCMSession

        session = RCMSession()
        session.scope.tag = "P-201A"
        dumped = session.model_dump(mode="json")
        restored = RCMSession.model_validate(dumped)
        assert restored.scope.tag == "P-201A"
        assert restored.schema_version == 1

    def test_future_schema_version_fails_loud_in_spanish(self):
        from rcm_runbook.agent.tools import _load
        from rcm_runbook.models.session import RCMSession

        class Ctx:
            session_state = {"rcm": {**RCMSession().model_dump(mode="json"),
                                     "schema_version": 99}}

        with pytest.raises(ValueError, match="esquema más nuevo"):
            _load(Ctx())
