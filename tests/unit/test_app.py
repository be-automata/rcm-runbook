"""AgentOS app construction + export download endpoint (P3b exit criteria)."""


import pytest

from rcm_runbook.config import settings
from rcm_runbook.export.excel import export_xlsx
from tests.unit.test_compliance import full_session


class TestApp:
    def test_agentos_routes_mounted(self, client):
        # AgentOS exposes an OpenAPI schema with its runtime endpoints
        # (el esquema exige llave: describe toda la superficie de la API)
        params = {"key": settings.os_security_key} if settings.os_security_key else {}
        schema = client.get("/openapi.json", params=params).json()
        paths = list(schema["paths"])
        assert any("agent" in p or "run" in p or "session" in p for p in paths), paths

    def test_download_serves_golden_export(self, client):
        path = export_xlsx(full_session(), settings.exports_dir, session_id="any-session")
        url = f"/exports/any-session/{path.name}"
        if settings.os_security_key:
            assert client.get(url).status_code == 401  # sin llave → rechazado
            resp = client.get(url, params={"key": settings.os_security_key})
        else:
            resp = client.get(url)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith(
            "application/vnd.openxmlformats-officedocument"
        )
        assert len(resp.content) > 5000

    def test_download_rejects_traversal(self, client):
        params = {"key": settings.os_security_key} if settings.os_security_key else {}
        traversal = client.get("/exports/s/..%2F..%2Fetc%2Fpasswd", params=params)
        assert traversal.status_code in (400, 404)
        assert client.get("/exports/s/no-existe.xlsx", params=params).status_code == 404
        assert client.get("/exports/s/archivo.txt", params=params).status_code == 400


class TestApiIsClosedByDefault:
    """La llave de AgnoAPISettings dejaba abiertas 22 rutas GET, entre ellas
    /sessions y /sessions/{id}/runs — o sea las transcripciones completas de
    cada análisis, legibles por cualquiera con la URL pública."""

    LEAKY = [
        "/sessions",
        "/sessions/cualquiera",
        "/sessions/cualquiera/runs",
        "/memories",
        "/metrics",
        "/traces",
        "/eval-runs",
        "/registry",
        "/info",
        "/user_memory_stats",
        "/trace_session_stats",
    ]

    @pytest.mark.parametrize("path", LEAKY)
    def test_sensitive_routes_require_key(self, client, con_llave, path):
        assert client.get(path).status_code == 401, f"{path} respondió sin llave"

    @pytest.mark.parametrize("path", LEAKY)
    def test_sensitive_routes_open_with_key(self, client, con_llave, path):
        resp = client.get(path, headers={"Authorization": f"Bearer {con_llave}"})
        assert resp.status_code != 401, f"{path} rechazó la llave válida"

    def test_wrong_key_is_rejected(self, client, con_llave):
        assert client.get("/sessions", headers={"Authorization": "Bearer no-es"}).status_code == 401
        assert client.get("/sessions", params={"key": "no-es"}).status_code == 401

    def test_demo_page_and_health_stay_public(self, client, con_llave):
        # El enlace del cliente carga la página sin llave; la página autentica
        # sus propias llamadas. Y el monitoreo necesita /health abierto.
        assert client.get("/demo").status_code == 200
        assert client.get("/health").status_code == 200

    @pytest.mark.parametrize("path", ["/demo/", "/health/", "/favicon.ico"])
    def test_trailing_slash_and_favicon_stay_public(self, client, con_llave, path):
        # Corremos por fuera del TrailingSlashMiddleware de agno: sin normalizar
        # la ruta, el cliente que escribe la URL con `/` final ve un JSON de error
        # en vez del chat, y Safari se lleva un 401 al pedir el favicon.
        assert client.get(path).status_code != 401, f"{path} exigió llave"

    def test_non_ascii_key_is_rejected_not_crashed(self, client, con_llave):
        # `compare_digest` sobre str revienta con no-ASCII: era un 500 con
        # traceback que cualquier anónimo disparaba desde internet.
        assert client.get("/sessions", params={"key": "café"}).status_code == 401
        # En la cabecera llega como bytes y uvicorn la decodifica latin-1
        assert client.get(
            "/sessions", headers={"Authorization": "Bearer ñ".encode("latin-1")}
        ).status_code == 401

    def test_real_preflight_passes_but_bare_options_does_not(self, client, con_llave):
        preflight = client.options(
            "/sessions",
            headers={
                "Origin": "https://os.agno.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert preflight.status_code != 401
        assert client.options("/sessions").status_code == 401

    def test_401_carries_cors_headers_for_allowed_origin(self, client, con_llave):
        # Envolvemos al CORSMiddleware: sin esto os.agno.com con la llave mala
        # ve un error opaco de CORS en vez del 401 en español.
        resp = client.get("/sessions", headers={"Origin": "https://os.agno.com"})
        assert resp.status_code == 401
        assert resp.headers.get("access-control-allow-origin") == "https://os.agno.com"

    def test_browser_links_accept_key_query_param(self, client, con_llave):
        # `?key=` debe valer en TODA la API, no solo en /exports: si algún día se
        # exporta OS_SECURITY_KEY al entorno, agno activa su propia dependencia
        # (solo Bearer) y estos enlaces mueren en 401. El contenedor recibe la
        # llave como RCM_OS_SECURITY_KEY justamente para evitarlo.
        assert client.get("/sessions", params={"key": con_llave}).status_code != 401
        assert client.get("/exports/x/y.xlsx", params={"key": con_llave}).status_code != 401

    def test_api_docs_are_not_public(self, client, con_llave):
        # El esquema describe toda la superficie de la API; no se regala.
        assert client.get("/openapi.json").status_code == 401
        assert client.get("/docs").status_code == 401


class TestWebsocketAuth:
    """El middleware `require_key` solo cubre HTTP: el handshake del WebSocket
    queda abierto a propósito, porque os.agno.com se autentica *dentro* del
    protocolo (manda {"action":"authenticate","token":…} ya conectado) y exigir
    la llave en el handshake rompería esa integración.

    Lo que sí debe cumplirse siempre: sin token no se ejecuta ninguna acción.
    Si una versión futura de Agno afloja eso, este test lo caza."""

    @pytest.fixture(autouse=True)
    def _requiere_llave_real(self):
        # agno lee la llave del AgnoAPISettings capturado al importar, así que
        # `con_llave` (que parchea `settings`) no sirve aquí: hace falta la real.
        if not settings.os_security_key:
            pytest.skip("no security key configured in this environment")

    def test_socket_opens_but_demands_auth(self, client):
        with client.websocket_connect("/workflows/ws") as ws:
            saludo = ws.receive_json()
            assert saludo.get("requires_auth") is True

    def test_actions_are_refused_without_token(self, client):
        with client.websocket_connect("/workflows/ws") as ws:
            ws.receive_json()
            ws.send_json({"action": "start_workflow", "workflow_id": "cualquiera"})
            assert ws.receive_json()["event"] == "auth_required"

    def test_wrong_token_is_refused(self, client):
        with client.websocket_connect("/workflows/ws") as ws:
            ws.receive_json()
            ws.send_json({"action": "authenticate", "token": "llave-falsa"})
            assert ws.receive_json()["event"] == "auth_error"

    def test_correct_token_authenticates(self, client):
        with client.websocket_connect("/workflows/ws") as ws:
            ws.receive_json()
            ws.send_json({"action": "authenticate", "token": settings.os_security_key})
            assert ws.receive_json()["event"] == "authenticated"


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


class TestExportsSurviveEphemeralDisk:
    """En Cloudflare Containers el disco se borra al dormir el contenedor. El
    entregable es función pura del estado de la sesión, así que se regenera
    desde la base en vez de conservarse en disco."""

    def test_regenerates_from_session_state_when_file_is_gone(self, client, tmp_path):
        from rcm_runbook import app as app_module
        from tests.unit.test_compliance import full_session

        sesion = full_session()
        guardado = {"session_data": {"session_state": {"rcm": sesion.model_dump(mode="json")}}}
        original = app_module.agent.db.get_session
        app_module.agent.db.get_session = lambda **kw: guardado
        try:
            tag = sesion.scope.tag
            generado = app_module._regenerar_entregable("s1", f"AMEF_{tag}.xlsx")
            assert generado is not None and generado.is_file()
            assert generado.stat().st_size > 5000
        finally:
            app_module.agent.db.get_session = original

    def test_unknown_session_or_filename_is_not_served(self, client):
        from rcm_runbook import app as app_module

        original = app_module.agent.db.get_session
        app_module.agent.db.get_session = lambda **kw: None
        try:
            assert app_module._regenerar_entregable("no-existe", "AMEF_X.xlsx") is None
        finally:
            app_module.agent.db.get_session = original


class TestDefinitiveExportKeepsItsGate:
    """El nombre del archivo lo elige quien arma la URL. Sin compuerta, quitar el
    prefijo BORRADOR_ entregaba un "definitivo" de un análisis a medias — justo
    lo que la norma prohíbe y lo que la herramienta de exportación sí bloquea."""

    def _con_sesion(self, monkeypatch, sesion):
        from rcm_runbook import app as app_module

        estado = {"session_state": {"rcm": sesion.model_dump(mode="json")}}
        monkeypatch.setattr(
            app_module.agent.db, "get_session", lambda **kw: {"session_data": estado}
        )
        return app_module

    def test_incomplete_session_cannot_yield_a_definitive_file(self, client, monkeypatch):
        from rcm_runbook.engine import compliance
        from rcm_runbook.models.session import RCMSession

        sesion = RCMSession()
        sesion.scope.tag = "P-999"
        assert compliance.export_blockers(sesion), "la sesión debía estar incompleta"
        app_module = self._con_sesion(monkeypatch, sesion)
        assert app_module._regenerar_entregable("s", "AMEF_P-999.xlsx") is None

    def test_incomplete_session_still_yields_a_draft(self, client, monkeypatch):
        from rcm_runbook.models.session import RCMSession

        sesion = RCMSession()
        sesion.scope.tag = "P-999"
        app_module = self._con_sesion(monkeypatch, sesion)
        borrador = app_module._regenerar_entregable("s", "BORRADOR_AMEF_P-999.xlsx")
        assert borrador is not None and borrador.is_file()

    def test_complete_session_yields_the_definitive_file(self, client, monkeypatch):
        from tests.unit.test_compliance import full_session

        sesion = full_session()
        app_module = self._con_sesion(monkeypatch, sesion)
        definitivo = app_module._regenerar_entregable("s", f"AMEF_{sesion.scope.tag}.xlsx")
        assert definitivo is not None and definitivo.is_file()


class TestExportNamesAreSane:
    def test_dot_names_are_rejected(self, client, con_llave):
        # `\w` dejaba pasar «.» y «..» como session_id. El cliente HTTP ya
        # normaliza esas rutas, así que aquí se comprueba el guardia directo.
        from rcm_runbook.app import _SAFE_NAME

        for malo in (".", "..", "..."):
            assert not _SAFE_NAME.match(malo), f"{malo} no fue rechazado"
        for bueno in ("demo-abc", "P-101", "a.b"):
            assert _SAFE_NAME.match(bueno), f"{bueno} fue rechazado por error"

    def test_favicon_is_served_not_404(self, client):
        r = client.get("/favicon.ico")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg")


class TestDatabaseBackendIsConfigurable:
    """Sin `DATABASE_URL` se usa SQLite (desarrollo). Con ella, Postgres — que es
    lo que sostiene la continuidad de sesión donde el disco no persiste."""

    def test_sqlite_by_default(self):
        from agno.db.sqlite import SqliteDb

        from rcm_runbook.agent.factory import build_db
        from rcm_runbook.config import Settings

        assert isinstance(build_db(Settings(db_url="")), SqliteDb)

    def test_postgres_when_database_url_is_set(self, monkeypatch):
        from rcm_runbook.agent import factory

        creada = {}

        class FalsaPostgresDb:
            def __init__(self, db_url):
                creada["url"] = db_url

        import agno.db.postgres as pg

        monkeypatch.setattr(pg, "PostgresDb", FalsaPostgresDb)
        from rcm_runbook.config import Settings

        factory.build_db(Settings(db_url="postgresql+psycopg://u:p@h/d"))
        assert creada["url"] == "postgresql+psycopg://u:p@h/d"


class TestCurrentExportRoute:
    """`/exports/{sesion}` sin nombre de archivo: lo que usa el botón de la
    página, porque el navegador no conoce el TAG del equipo."""

    def _con_sesion(self, monkeypatch, sesion):
        from rcm_runbook import app as app_module

        estado = {"session_state": {"rcm": sesion.model_dump(mode="json")}}
        monkeypatch.setattr(
            app_module.agent.db, "get_session", lambda **kw: {"session_data": estado}
        )

    def test_complete_session_gets_the_definitive_file(self, client, con_llave, monkeypatch):
        from tests.unit.test_compliance import full_session

        sesion = full_session()
        self._con_sesion(monkeypatch, sesion)
        r = client.get("/exports/s1", params={"key": con_llave})
        assert r.status_code == 200
        assert f'filename="AMEF_{sesion.scope.tag}.xlsx"' in r.headers["content-disposition"]
        assert len(r.content) > 5000

    def test_incomplete_session_gets_a_clearly_marked_draft(self, client, con_llave, monkeypatch):
        from rcm_runbook.models.session import RCMSession

        sesion = RCMSession()
        sesion.scope.tag = "P-999"
        self._con_sesion(monkeypatch, sesion)
        r = client.get("/exports/s1", params={"key": con_llave})
        assert r.status_code == 200
        assert 'filename="BORRADOR_AMEF_P-999.xlsx"' in r.headers["content-disposition"]

    def test_session_without_tag_explains_instead_of_failing(self, client, con_llave, monkeypatch):
        from rcm_runbook.models.session import RCMSession

        self._con_sesion(monkeypatch, RCMSession())
        r = client.get("/exports/s1", params={"key": con_llave})
        assert r.status_code == 404
        assert "nada que exportar" in r.json()["detail"]

    def test_requires_the_key(self, client, con_llave):
        assert client.get("/exports/s1").status_code == 401
