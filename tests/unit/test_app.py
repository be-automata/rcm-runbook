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

    def test_download_serves_golden_export(self, client, monkeypatch):
        # El definitivo exige que la sesión exista y esté completa: el archivo en
        # disco es una foto, el estado de la sesión es la verdad.
        from rcm_runbook import app as app_module

        sesion = full_session()
        estado = {"session_state": {"rcm": sesion.model_dump(mode="json")}}
        monkeypatch.setattr(
            app_module.agent.db, "get_session", lambda **kw: {"session_data": estado}
        )
        path = export_xlsx(sesion, settings.exports_dir, session_id="any-session")
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


class TestStaleDefinitiveIsNotServedFromDisk:
    """El archivo en disco es una foto del pasado. Si la sesión retrocedió de
    fase, ese `AMEF_` definitivo ya no debe entregarse: manda el estado actual."""

    def test_disk_file_is_ignored_when_session_became_incomplete(
        self, client, con_llave, monkeypatch, tmp_path
    ):
        from rcm_runbook import app as app_module
        from rcm_runbook.export.excel import export_xlsx
        from rcm_runbook.models.session import RCMSession
        from tests.unit.test_compliance import full_session

        completa = full_session()
        app_module.settings.exports_dir = str(tmp_path)
        escrito = export_xlsx(completa, tmp_path, session_id="s-vieja")

        # la sesión retrocede: ahora está incompleta
        incompleta = RCMSession()
        incompleta.scope.tag = completa.scope.tag
        estado = {"session_state": {"rcm": incompleta.model_dump(mode="json")}}
        monkeypatch.setattr(
            app_module.agent.db, "get_session", lambda **kw: {"session_data": estado}
        )
        assert escrito.is_file(), "el definitivo sigue en disco"
        r = client.get(f"/exports/s-vieja/{escrito.name}", params={"key": con_llave})
        assert r.status_code == 404, "sirvió un definitivo obsoleto desde disco"


class TestTempFilesAreCleanedUp:
    """Cada regeneración crea un mkdtemp; sin limpiarlo, cada clic del botón
    dejaba ~11 KB permanentes en el disco del contenedor."""

    def test_regenerated_download_removes_its_temp_dir(self, client, con_llave, monkeypatch):
        import glob

        from rcm_runbook import app as app_module
        from rcm_runbook.models.session import RCMSession

        sesion = RCMSession()
        sesion.scope.tag = "P-777"
        estado = {"session_state": {"rcm": sesion.model_dump(mode="json")}}
        monkeypatch.setattr(
            app_module.agent.db, "get_session", lambda **kw: {"session_data": estado}
        )
        antes = set(glob.glob("/tmp/rcm-export-*"))
        r = client.get("/exports/s-temp", params={"key": con_llave})
        assert r.status_code == 200
        despues = set(glob.glob("/tmp/rcm-export-*"))
        assert despues <= antes, f"quedaron temporales sin borrar: {despues - antes}"


class TestExportsDirEsEscribible:
    """La imagen corría con /app propiedad de root y el proceso como uid 10001,
    así que `export_excel` moría con «Permission denied: 'data'»: la descarga
    por chat estaba rota en producción mientras la del botón funcionaba."""

    def test_el_dockerfile_da_permisos_al_directorio_de_trabajo(self):
        from pathlib import Path

        dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
        assert "chown -R rcm:rcm /app" in dockerfile, (
            "sin esto el proceso no puede crear data/exports y export_excel falla"
        )

    def test_la_herramienta_escribe_donde_apunta_la_config(self, tmp_path, monkeypatch):
        from rcm_runbook.config import settings as cfg
        from rcm_runbook.export.excel import export_xlsx
        from tests.unit.test_compliance import full_session

        monkeypatch.setattr(cfg, "exports_dir", str(tmp_path / "sin-crear"))
        generado = export_xlsx(full_session(), cfg.exports_dir, session_id="s1")
        assert generado.is_file() and generado.stat().st_size > 5000


class TestEnlaceDeExportSinLlave:
    """La herramienta incrustaba la llave en el enlace que ve el cliente, y esa
    transcripción se guarda en Postgres. Además el modelo evitaba repetir un
    enlace con un secreto dentro, así que el cliente se quedaba sin nada que
    pulsar. Ahora el enlace es relativo y la página lo descarga autenticada."""

    def test_el_enlace_no_contiene_la_llave(self, tmp_path, monkeypatch):
        from rcm_runbook.agent import tools as tools_mod
        from rcm_runbook.config import settings as cfg
        from tests.unit.test_compliance import full_session

        monkeypatch.setattr(cfg, "exports_dir", str(tmp_path))
        monkeypatch.setattr(cfg, "os_security_key", "OSK_secreta_de_prueba")

        class Ctx:
            session_id = "s-enlace"
            session_state = {"rcm": full_session().model_dump(mode="json")}

        salida = tools_mod.export_excel.entrypoint(Ctx(), draft=True)
        assert "OSK_secreta_de_prueba" not in salida, "la llave se filtró al chat"
        assert "key=" not in salida
        assert "[Descargar el Excel](/exports/" in salida, salida


class TestCodigoIsoAusenteNoEsFalloTecnico:
    """Un código fuera del catálogo se propagaba como KeyError, y
    `_spanish_errors` lo disfrazaba de «❌ No se pudo completar la operación».
    El agente lo leía como avería del sistema y se inventaba la causa. La
    confusión nacía en la capa de herramientas, no en el modelo."""

    def _ctx(self):
        class Ctx:
            session_id = "s"
            session_state: dict = {}

        return Ctx()

    def test_devuelve_un_mensaje_de_negocio_no_el_banner_de_fallo(self):
        from rcm_runbook.agent import tools as tools_mod

        salida = tools_mod.explain_iso_code.entrypoint(self._ctx(), code="ZZZZ99")
        assert "❌" not in salida, "un código ausente no es un fallo del sistema"
        assert "no está en el catálogo" in salida
        assert "Códigos disponibles" in salida

    def test_un_codigo_valido_sigue_explicandose(self):
        from rcm_runbook.agent import tools as tools_mod
        from rcm_runbook.models.catalogs import fixture

        valido = fixture().menu.iso14224_failure_mode_codes[0].code
        salida = tools_mod.explain_iso_code.entrypoint(self._ctx(), code=valido)
        assert salida.startswith(valido) and "❌" not in salida

    def test_el_enlace_no_expone_la_ruta_del_contenedor(self):
        from rcm_runbook.agent import tools as tools_mod
        from tests.unit.test_compliance import full_session

        class Ctx:
            session_id = "s-ruta"
            session_state = {"rcm": full_session().model_dump(mode="json")}

        salida = tools_mod.export_excel.entrypoint(Ctx(), draft=True)
        assert "data/exports/" not in salida, "expone la ruta interna del contenedor"


class TestGetProgressNoSeUsaComoCompuerta:
    """El validador midió 3 de 3 rechazos inventados del entregable; con la
    instrucción reforzada, 2 de 3. El modelo decide leyendo la salida de
    `get_progress`, no el system prompt, así que el aviso tiene que viajar ahí."""

    def test_la_salida_desmarca_sus_pendientes_como_bloqueadores_del_export(self):
        from rcm_runbook.agent import tools as tools_mod

        class Ctx:
            session_id = "s-prog"
            session_state: dict = {}

        salida = tools_mod.get_progress.entrypoint(Ctx())
        assert "SOLO de la fase actual" in salida
        assert "export_excel" in salida, "no dirige a la herramienta que decide"


class TestUnRechazoDelMetodoNoEsUnaAveria:
    """El agente trata «❌ No se pudo completar la operación» como sistema roto:
    deja de trabajar, avisa de un fallo técnico y se inventa la causa. Varias
    herramientas emitían ese banner —algunas en inglés— ante datos que
    simplemente no valen. Es la diferencia entre «esto se rompió» y «ese dato
    no es el que va»."""

    BANNER = "No se pudo completar la operación"

    def _ctx(self):
        class Ctx:
            session_id = "s-neg"
            session_state: dict = {}

        return Ctx()

    def test_metodo_de_ffi_escrito_en_espanol(self):
        from rcm_runbook.agent import tools as tools_mod

        salida = tools_mod.calculate_ffi.entrypoint(
            self._ctx(), method="disponibilidad", u_fraction=0.02, mtive_hours=8760
        )
        assert self.BANNER not in salida
        assert "availability" in salida, "no dice cuál es el método correcto"
        # Sin el banner pero en inglés seguiría siendo un mensaje del motor
        # colado en una conversación en español (criterio 1 del UAT).
        assert "expected one of" not in salida
        assert "Método de FFI desconocido" in salida

    def test_lista_de_mted_no_numerica(self):
        from rcm_runbook.agent import tools as tools_mod

        salida = tools_mod.calculate_ffi.entrypoint(
            self._ctx(), method="multi_single",
            mted_list_hours="ocho,diez", mtive_hours=8760, mmf_hours=100,
        )
        assert self.BANNER not in salida
        assert "could not convert" not in salida, "fuga del mensaje de Python"

    def test_rango_invalido_se_explica_en_espanol(self):
        from rcm_runbook.agent import tools as tools_mod

        salida = tools_mod.calculate_ffi.entrypoint(
            self._ctx(), method="availability", u_fraction=0.0, mtive_hours=8760
        )
        assert self.BANNER not in salida
        assert "open interval" not in salida, "el mensaje del motor sale en inglés"
        assert "entre 0 y 1" in salida

    def test_tipo_de_funcion_fuera_del_catalogo(self):
        from rcm_runbook.agent import tools as tools_mod

        salida = tools_mod.confirm_no_functions.entrypoint(
            self._ctx(), kind="secundarias_raras"
        )
        assert self.BANNER not in salida
        assert "is not a valid FunctionKind" not in salida
        assert "proteccion" in salida, "no ofrece los tipos válidos"

    def test_un_fallo_tecnico_de_verdad_sigue_llevando_su_banner(self):
        # El contrapeso: si todo dejara de ser técnico, el agente ya no podría
        # distinguir una avería real y la callaría.
        from rcm_runbook.agent import tools as tools_mod

        class Rota:
            session_id = "s"

            @property
            def session_state(self):
                raise RuntimeError("el almacén de sesiones no responde")

        salida = tools_mod.get_progress.entrypoint(Rota())
        assert self.BANNER in salida

    def test_un_dato_invalido_pide_corregir_no_avisar_a_soporte(self):
        from rcm_runbook.agent import tools as tools_mod

        salida = tools_mod.record_task.entrypoint(
            self._ctx(), failure_mode_id="FM-001", description="x",
            frequency="Diaria", duration_hours=1, discipline="mecanica",
        )
        assert self.BANNER not in salida
        assert "corrija y reintente" in salida
        assert "Diario" in salida, "no ofrece la frecuencia válida del catálogo"


class TestElCatalogoIsoLlegaComoLista:
    """La salida de la herramienta se mantiene en lista aunque el renderizador
    ya dibuje tablas: es lo que el modelo copia, y una lista se lee igual de
    bien en el chat y en el Excel exportado."""

    def test_la_herramienta_devuelve_lista_no_tabla(self):
        from rcm_runbook.agent import tools as tools_mod

        class Ctx:
            session_id = "s-iso"
            session_state: dict = {}

        salida = tools_mod.explain_iso_code.entrypoint(Ctx(), code="QQQ1")
        assert "|" not in salida
        assert "- FTS — " in salida


class TestElPlanNoSaleConTareasContradictorias:
    """El primer análisis completo real produjo dos filas para el mismo modo,
    una «1 h, sin paro» y otra «3 h, requiere paro», y la hoja AMEF mostró en
    silencio la equivocada. El guardián prometía «near-duplicate» en su docstring
    y comparaba texto exacto: bastaba con reformular para colarse."""

    def _sesion_con_un_modo(self):
        from tests.unit.test_compliance import full_session

        s = full_session()
        fm = next(iter(s.failure_modes))
        s.tasks.pop(fm, None)
        return s, fm

    def _tarea(self, fm, descripcion, **campos):
        from rcm_runbook.models.domain import MaintenanceTask

        base = {
            "failure_mode_id": fm, "description": descripcion, "frequency": "Mensual",
            "duration_hours": 1.0, "discipline": "Mecánico", "requires_shutdown": False,
        }
        base.update(campos)
        return MaintenanceTask(**base)

    def test_el_reintento_literal_sigue_siendo_idempotente(self):
        s, fm = self._sesion_con_un_modo()
        s.add_task(self._tarea(fm, "Inspeccionar rodamientos"))
        s.add_task(self._tarea(fm, "  inspeccionar  RODAMIENTOS "))
        assert len(s.tasks[fm]) == 1, "el reintento del LLM duplicó la tarea"

    def test_una_reformulacion_no_se_cuela_como_tarea_nueva(self):
        import pytest

        from rcm_runbook.errors import ReglaDeNegocio

        s, fm = self._sesion_con_un_modo()
        s.add_task(self._tarea(fm, "Inspeccionar rodamientos de bomba P-101"))
        with pytest.raises(ReglaDeNegocio) as exc:
            s.add_task(self._tarea(
                fm, "Inspeccionar rodamientos de bomba P-101 (cojinetes motor y bomba)",
                duration_hours=3.0, requires_shutdown=True,
            ))
        assert "casi idéntica" in str(exc.value)
        assert "requiere paro" in str(exc.value), "no muestra en qué se contradicen"
        assert len(s.tasks[fm]) == 1

    def test_misma_descripcion_con_otros_datos_no_se_descarta_en_silencio(self):
        # Es una corrección, no un reintento: quedarse con la primera deja el
        # dato viejo justo cuando alguien intentaba arreglarlo.
        import pytest

        from rcm_runbook.errors import ReglaDeNegocio

        s, fm = self._sesion_con_un_modo()
        s.add_task(self._tarea(fm, "Termografía del tablero"))
        with pytest.raises(ReglaDeNegocio):
            s.add_task(self._tarea(fm, "Termografía del tablero", duration_hours=4.0))

    def test_dos_tareas_de_verdad_distintas_conviven(self):
        # El contrapeso: fusionar de más borraría una tarea legítima del plan.
        s, fm = self._sesion_con_un_modo()
        s.add_task(self._tarea(fm, "Inspeccionar rodamientos"))
        s.add_task(self._tarea(fm, "Lubricar acoples", discipline="Mecánico"))
        s.add_task(self._tarea(fm, "Análisis de vibraciones del motor"))
        assert len(s.tasks[fm]) == 3


class TestLasSiglasVanConSuDefinicion:
    """Tercera y cuarta instancia del mismo defecto: donde la herramienta da una
    sigla pelada, el modelo inventa su significado. Con los códigos ISO se midió
    (5 códigos, 3 corridas, 15/15 mal); con los métodos de FFI, 4 corridas y 4
    significados distintos, ninguno correcto — y ahí lo inventado fija cada
    cuánto se prueba un dispositivo de seguridad."""

    def test_el_rechazo_de_ffi_explica_cada_metodo(self):
        # Las CINCO definiciones, cada una pegada a SU método: la primera
        # versión comprobaba los identificadores y una sola definición suelta,
        # así que intercambiar los significados de multi_single y single_multi
        # pasaba desapercibido.
        from rcm_runbook.agent import tools as tools_mod
        from rcm_runbook.agent.tools import METODOS_FFI

        class Ctx:
            session_id = "s-ffi"
            session_state: dict = {}

        salida = tools_mod.calculate_ffi.entrypoint(Ctx(), method="disponibilidad")
        for metodo, definicion in METODOS_FFI:
            assert f"- {metodo} — {definicion}" in salida, f"{metodo} sin su definición"

    def test_cada_metodo_de_ffi_dice_lo_que_hace_el_motor(self):
        # Contra el motor, no contra sí mismo: intercambiar las definiciones de
        # multi_single y single_multi en la tabla Y en el docstring dejaba la
        # suite en verde, y es justo el error que contamina un cálculo de
        # seguridad.
        from rcm_runbook.agent.tools import METODOS_FFI

        tabla = dict(METODOS_FFI)
        assert "VARIAS funciones protegidas, UN SOLO dispositivo" == tabla["multi_single"]
        assert "UNA función protegida, VARIOS dispositivos redundantes" == (
            tabla["single_multi"]
        )
        # La verdad vive en engine/ffi.py: multi_single recibe una LISTA de
        # Mted (varias funciones protegidas); single_multi recibe n (varios
        # dispositivos).
        import inspect

        from rcm_runbook.engine import ffi

        assert "mted_list" in inspect.signature(ffi.ffi_multi_single).parameters
        assert "n" in inspect.signature(ffi.ffi_single_multi).parameters

    def test_los_parametros_llegan_al_motor_por_el_camino_correcto(self):
        # Intercambiar el enrutado real (mted_list ↔ n) daba otro número con un
        # ✔ delante y ningún test lo miraba.
        from rcm_runbook.agent import tools as tools_mod

        class Ctx:
            session_id = "s-ffi2"
            session_state: dict = {}

        multi = tools_mod.calculate_ffi.entrypoint(
            Ctx(), method="multi_single", mtive_hours=43800,
            mted_list_hours="8760,17520", mmf_hours=100000,
        )
        single = tools_mod.calculate_ffi.entrypoint(
            Ctx(), method="single_multi", mtive_hours=43800, mted_hours=8760,
            mmf_hours=100000, n_devices=2,
        )
        assert "❌" not in multi and "❌" not in single
        # Los dos métodos son fórmulas distintas: si el enrutado se cruzara,
        # darían el mismo número o uno de los dos fallaría.
        assert multi != single

    def test_el_docstring_define_los_parametros_que_se_inventaban(self):
        # Es lo que el modelo lee antes de preguntar. `cff` se leyó como
        # «coeficiente adimensional» y `mtive` como «duración de la prueba».
        from rcm_runbook.agent import tools as tools_mod

        doc = tools_mod.calculate_ffi.entrypoint.__doc__ or ""
        assert "COSTO en dinero de ejecutar una búsqueda" in doc
        assert "TPEF del DISPOSITIVO DE PROTECCIÓN" in doc
        assert "No es la duración de la prueba" in doc

    def test_la_politica_de_mantenimiento_no_llega_como_acronimo_pelado(self):
        # Ejecutando la herramienta, no leyendo su código: la primera versión de
        # este test miraba el fuente y sobrevivía a la mutación que devolvía el
        # acrónimo pelado.
        from rcm_runbook.agent import tools as tools_mod
        from tests.unit.test_compliance import full_session

        sesion = full_session()
        fm = next(iter(sesion.failure_modes))

        class Ctx:
            session_id = "s-pol"
            session_state = {"rcm": sesion.model_dump(mode="json")}

        salida = tools_mod.run_decision_logic.entrypoint(
            Ctx(), failure_mode_id=fm, pf_interval_sufficient=True,
            approver="Ana Pérez, Supervisora HSE",
        )
        from rcm_runbook.models.catalogs import POLICY_LABELS_ES

        # Contra el nombre real, no contra «hay un paréntesis»: la primera
        # versión de esta aserción se conformaba con el «(» de «(consecuencia:»
        # y sobrevivía a la mutación que devolvía el acrónimo pelado.
        assert any(n in salida for n in POLICY_LABELS_ES.values()), (
            f"la política llegó como acrónimo pelado: {salida[:100]}"
        )

    def test_sin_politica_determinable_no_es_una_averia(self):
        # El motor está diciendo qué falta preguntarle al equipo. Con el banner
        # técnico delante, el agente lo leía como sistema roto y se paraba.
        from rcm_runbook.agent import tools as tools_mod
        from tests.unit.test_compliance import full_session

        sesion = full_session()
        fm = next(iter(sesion.failure_modes))

        class Ctx:
            session_id = "s-nopol"
            session_state = {"rcm": sesion.model_dump(mode="json")}

        salida = tools_mod.run_decision_logic.entrypoint(Ctx(), failure_mode_id=fm)
        assert "No se pudo completar la operación" not in salida
        assert "No hay política determinable" in salida


def _registrar_integrante(tools_mod, ctx, nombre: str) -> str:
    """Fuera del bucle a propósito: un lambda que captura la variable de la
    iteración es justo la clase de cierre que ya causó la fuga de la llave."""
    return tools_mod.record_team_member.entrypoint(ctx, name=nombre, role="Operador")


class TestNoSePierdenEscriturasEnParalelo:
    """En producción `score_risk` contestó «✔ Riesgo inicial de FM-002:
    S9-O3-D8 → RPN=216» y seis turnos después el entregable se bloqueó porque
    FM-002 no tenía valoración: el dato de riesgo de un modo con S=9 se evaporó
    con un ✔ delante.

    `_load` lee el estado, la herramienta muta una copia y `_save` reescribe el
    objeto entero. Con dos llamadas del mismo turno en paralelo, la segunda
    parte de la foto vieja y borra a la primera.

    La carrera NO se reproduce sola: en local el load-mutate-save dura
    microsegundos y las hebras casi nunca se solapan — probado, con 24 hebras y
    el candado quitado no se perdía ni una. Por eso se fuerza el solapamiento
    con una barrera: las hebras se esperan unas a otras DENTRO de la lectura,
    que es justo la ventana del defecto. Con el candado puesto no pueden
    coincidir ahí, la barrera vence por tiempo y cada una escribe en su turno.
    """

    HEBRAS = 4

    def _contexto(self):
        import threading

        barrera = threading.Barrier(self.HEBRAS, timeout=0.15)

        class EstadoConBarrera(dict):
            def get(self, clave, defecto=None):
                # La espera va DESPUÉS de leer: así todas se llevan la misma
                # foto vieja y la carrera es segura, no cuestión de suerte.
                # Con la barrera antes de la lectura el defecto solo aparecía
                # 1 de cada 5 veces, porque una hebra terminaba su turno entero
                # antes de que la siguiente llegara a leer.
                valor = super().get(clave, defecto)
                try:
                    barrera.wait()
                except threading.BrokenBarrierError:
                    pass  # el candado hizo su trabajo: no pudieron coincidir
                return valor

        class Ctx:
            session_id = "s-carrera"
            session_state = EstadoConBarrera()

        return Ctx()

    def test_registros_simultaneos_no_se_pisan(self):
        # Cinco rondas: con una sola, quitar el candado fallaba 2 de 3 veces, y
        # un test que deja pasar el defecto un tercio de las veces no sirve de
        # red. Con cinco, que las cinco se salven por casualidad es despreciable.
        import concurrent.futures as cf
        import functools

        from rcm_runbook.agent import tools as tools_mod
        from rcm_runbook.models.session import RCMSession

        for ronda in range(5):
            ctx = self._contexto()
            nombres = [f"Persona {ronda}-{i}" for i in range(self.HEBRAS)]
            with cf.ThreadPoolExecutor(max_workers=self.HEBRAS) as pool:
                list(pool.map(
                    functools.partial(_registrar_integrante, tools_mod, ctx), nombres
                ))

            guardada = RCMSession.model_validate(ctx.session_state["rcm"])
            perdidos = set(nombres) - {m.name for m in guardada.team}
            assert not perdidos, (
                f"ronda {ronda}: se perdieron {len(perdidos)} de {len(nombres)} "
                f"escrituras: {sorted(perdidos)}"
            )

    def test_el_candado_es_por_sesion_no_global(self):
        # Serializar TODAS las sesiones convertiría el candado en un cuello de
        # botella para todos los clientes a la vez.
        from rcm_runbook.agent.tools import _candado

        class A:
            session_id = "sesion-a"

        class B:
            session_id = "sesion-b"

        assert _candado(A()) is not _candado(B())
        assert _candado(A()) is _candado(A())


class TestElNucleoDeLaTareaMandaSobreLosArticulos:
    """Se coló hasta el Excel del cliente quitando dos artículos: «…de los
    rodamientos de la bomba P-101» frente a «…de rodamientos de bomba P-101».
    Y a la vez rechazaba de más: «Análisis de aceite» se tomaba por «Análisis de
    vibración»."""

    BASE = "Análisis de vibración de los rodamientos de la bomba P-101"

    def _casi(self, otro: str) -> bool:
        from rcm_runbook.models.session import RCMSession

        return RCMSession._casi_igual(self.BASE, otro)

    def test_quitar_articulos_no_cuela_una_tarea_nueva(self):
        assert self._casi("Análisis de vibración de rodamientos de bomba P-101")

    def test_el_plural_no_cuela_una_tarea_nueva(self):
        assert self._casi("Análisis de vibraciones de los rodamientos de bomba P-101")

    def test_una_cola_de_relleno_no_desactiva_el_guardian(self):
        # Añadir veinte palabras idénticas diluía el Jaccard bajo el umbral.
        assert self._casi(self.BASE + " durante el turno de mañana con el equipo "
                          "de predictivo presente y su registro correspondiente")

    def test_una_tarea_legitimamente_distinta_no_se_rechaza(self):
        for otra in (
            "Análisis de aceite de los rodamientos de la bomba P-101",
            "Lubricación de los rodamientos de la bomba P-101",
            "Termografía del tablero eléctrico",
            "Alineación láser del acople de la bomba P-101",
        ):
            assert not self._casi(otra), f"rechazó de más: {otra}"


class TestElPlanContradictorioNoSePuedeExportar:
    """La red que sí es determinista. El guardián de texto no puede cazar un
    sinónimo sin rechazar tareas legítimas; esto no adivina si son la misma
    tarea, solo se niega a entregar un plan donde dos filas del mismo modo
    mandan cosas distintas."""

    def _con_dos_tareas(self, **segunda):
        from rcm_runbook.models.domain import MaintenanceTask
        from tests.unit.test_compliance import full_session

        s = full_session()
        fm = next(iter(s.failure_modes))
        s.tasks[fm] = []
        base = {
            "failure_mode_id": fm, "frequency": "Mensual", "duration_hours": 2.0,
            "discipline": "Mecánico", "requires_shutdown": False,
        }
        s.tasks[fm].append(MaintenanceTask(
            description="Análisis de vibración de los rodamientos de la bomba P-101",
            **base,
        ))
        s.tasks[fm].append(MaintenanceTask(**{**base, **segunda}))
        return s, fm

    def test_dos_tareas_que_se_contradicen_bloquean_el_entregable(self):
        from rcm_runbook.engine import compliance

        s, fm = self._con_dos_tareas(
            description="Análisis de vibraciones de rodamientos de bomba P-101",
            requires_shutdown=True,
            duration_hours=3.0, frequency="Semestral",
        )
        bloqueos = compliance.export_blockers(s)
        contradiccion = [b for b in bloqueos if "se contradicen" in b]
        assert contradiccion, f"el plan contradictorio se exporta: {bloqueos}"
        assert fm in contradiccion[0]
        # Los cuatro campos, no solo el paro: comparar uno solo cazaba el
        # incidente original por casualidad.
        for etiqueta in ("frecuencia", "duración", "requiere paro"):
            assert etiqueta in contradiccion[0], f"no señala {etiqueta}"

    def test_solo_la_frecuencia_distinta_ya_contradice_el_plan(self):
        # El caso que se colaba hasta el .xlsx: sinónimo + dos periodicidades
        # para el mismo trabajo, con el mismo requires_shutdown.
        from rcm_runbook.engine import compliance

        s, _ = self._con_dos_tareas(
            description="Análisis de vibraciones de rodamientos de bomba P-101",
            frequency="Semestral",
        )
        bloqueos = [b for b in compliance.export_blockers(s) if "se contradicen" in b]
        assert bloqueos, "dos periodicidades para el mismo modo llegan al CMMS"
        assert "frecuencia" in bloqueos[0]

    def test_solo_el_ejecutor_distinto_ya_contradice_el_plan(self):
        from rcm_runbook.engine import compliance

        s, _ = self._con_dos_tareas(
            description="Análisis de vibraciones de rodamientos de bomba P-101",
            discipline="Instrumentista",
        )
        assert [b for b in compliance.export_blockers(s) if "ejecutor" in b]

    def test_dos_tareas_compatibles_no_bloquean(self):
        # El contrapeso: un modo puede llevar varias tareas legítimas, y
        # bloquear por tenerlas dejaría el producto inservible.
        from rcm_runbook.engine import compliance

        s, _ = self._con_dos_tareas(
            description="Lubricación de los rodamientos de la bomba P-101",
            frequency="Semestral",
            duration_hours=1.0,
        )
        assert not [b for b in compliance.export_blockers(s) if "se contradicen" in b]


class TestLaLetraDeRutaNoViajaSola:
    """Quinta instancia del patrón. Tres corridas en producción dieron tres
    alfabetos contradictorios: una invirtió las dos familias y glosó «CC» como
    «Consecuencias Catastróficas» (real: Control de Calidad). La letra va al
    entregable del cliente y es la traza auditable de por qué se eligió una
    política, así que inventarla contamina la auditoría."""

    def test_la_ruta_llega_con_su_significado(self):
        from rcm_runbook.agent import tools as tools_mod
        from tests.unit.test_compliance import full_session

        sesion = full_session()
        fm = next(iter(sesion.failure_modes))

        class Ctx:
            session_id = "s-ruta"
            session_state = {"rcm": sesion.model_dump(mode="json")}

        salida = tools_mod.run_decision_logic.entrypoint(
            Ctx(), failure_mode_id=fm, pf_interval_sufficient=True,
            approver="Ana Pérez, Supervisora HSE",
        )
        from rcm_runbook.models.catalogs import ROUTE_LABELS_ES

        assert any(n in salida for n in ROUTE_LABELS_ES.values()), (
            f"la ruta llegó como letra pelada: {salida[:120]}"
        )

    def test_estan_las_siete_letras_de_las_dos_familias(self):
        from rcm_runbook.models.catalogs import (
            ROUTE_LABELS_ES,
            EvidentRoute,
            HiddenRoute,
        )

        for r in list(EvidentRoute) + list(HiddenRoute):
            assert r.value in ROUTE_LABELS_ES, f"la ruta {r.value} no tiene significado"

    def test_la_A_es_seguridad_en_ambas_familias(self):
        # Una corrida racionalizó la colisión con «Parecen iguales pero no lo
        # son». Sí lo son: A es seguridad/ambiente en las dos.
        from rcm_runbook.models.catalogs import ROUTE_LABELS_ES

        assert "Seguridad" in ROUTE_LABELS_ES["A"]
        assert "oculta" in ROUTE_LABELS_ES["E"] and "Operacional" in ROUTE_LABELS_ES["E"]
        assert "evidente" in ROUTE_LABELS_ES["B"]


class TestLaCausaNoSeCuelaSinTilde:
    """`cause_must_differ_from_mode` bajaba a minúsculas pero no quitaba
    acentos, así que el modo LITERAL escrito sin tildes pasaba como causa."""

    def _crear(self, causa: str):
        from rcm_runbook.models.domain import FailureMode

        return FailureMode(
            id="FM-001", functional_failure_id="FF-001",
            description="Falla de rodamientos con vibración creciente",
            mechanism="Desgaste abrasivo", iso_code="VIB", cause=causa,
            root_cause="Intervalo de relubricación excedido",
            failure_pattern="Fin de Vida Útil",
        )

    def test_el_modo_sin_tildes_no_pasa_como_causa(self):
        import pytest

        with pytest.raises(ValueError, match="reformulación del modo"):
            self._crear("falla de rodamientos con vibracion creciente")

    def test_el_modo_con_tildes_sigue_sin_pasar(self):
        import pytest

        with pytest.raises(ValueError, match="reformulación del modo"):
            self._crear("Falla de rodamientos con vibración creciente")

    def test_una_causa_de_verdad_sigue_aceptandose(self):
        assert self._crear("Lubricante degradado por contaminación con agua")


class TestElUmbralDeCasiIgualEstaFijado:
    """El número que decide si dos tareas son la misma no tenía un solo assert:
    toda la rama difusa era código sin cubrir, y `_sin_acentos` podía ser la
    identidad con las 316 en verde."""

    def _casi(self, a: str, b: str) -> bool:
        from rcm_runbook.models.session import RCMSession

        return RCMSession._casi_igual(a, b)

    def test_los_acentos_no_distinguen_dos_tareas(self):
        assert self._casi("Termografía del tablero", "Termografia del tablero")

    def test_justo_en_el_umbral_es_la_misma_tarea(self):
        # Jaccard = |comunes| / |unión|. Cuatro palabras comunes y cinco en la
        # unión = 0.8 exacto, que es el umbral. Reordenadas para que no sea una
        # subcadena de la otra, o entraría por el camino del containment y el
        # umbral seguiría sin probarse.
        assert self._casi(
            "inspeccionar rodamiento bomba motor acople",
            "bomba inspeccionar rodamiento motor",
        )

    def test_por_debajo_del_umbral_son_tareas_distintas(self):
        # Tres comunes y cinco en la unión = 0.6: no puede fusionarlas.
        assert not self._casi(
            "inspeccionar rodamiento bomba motor acople",
            "bomba inspeccionar rodamiento",
        )

    def test_una_descripcion_vacia_no_se_parece_a_nada(self):
        assert not self._casi("", "Inspeccionar rodamientos")
        assert not self._casi("   ", "   ")

    def test_los_campos_comparados_son_todos_los_que_cambian_el_plan(self):
        # Reducir la lista a duration_hours devolvía el defecto entero: una
        # corrección de frecuencia, disciplina o paro se tragaba en silencio.
        import inspect

        from rcm_runbook.models.session import RCMSession

        fuente = inspect.getsource(RCMSession.add_task)
        for campo in ("frequency", "duration_hours", "discipline", "requires_shutdown"):
            assert campo in fuente, f"{campo} no se compara: una corrección se perdería"


class TestLaHojaAmefNoCallaTareas:
    """La hoja que el cliente abre primero mostraba `tasks[0]` y callaba el
    resto — en el caso real, callaba justo la corregida. Ninguna heurística de
    texto caza un sinónimo sin rechazar tareas legítimas, así que la garantía
    que sí es absoluta es esta: lo registrado no desaparece del entregable."""

    def _con_dos_tareas(self):
        from rcm_runbook.models.domain import MaintenanceTask
        from tests.unit.test_compliance import full_session

        s = full_session()
        fm = next(iter(s.failure_modes))
        base = {
            "failure_mode_id": fm, "duration_hours": 2.0,
            "discipline": "Mecánico", "requires_shutdown": False,
        }
        s.tasks[fm] = [
            MaintenanceTask(description="Análisis de vibración", frequency="Mensual", **base),
            MaintenanceTask(description="Termografía del motor", frequency="Semestral", **base),
        ]
        return s, fm

    def test_las_dos_tareas_aparecen_en_la_hoja_amef(self):
        from rcm_runbook.export.rows import to_amef_rows

        s, fm = self._con_dos_tareas()
        fila = next(f for f in to_amef_rows(s) if True)
        texto = " ".join(str(v) for v in fila.model_dump().values())
        assert "Análisis de vibración" in texto
        assert "Termografía del motor" in texto, "la hoja AMEF calló una tarea"

    def test_manda_al_plan_en_vez_de_inventar_una_frecuencia(self):
        # Con dos frecuencias distintas, elegir una sería mentir; y dejarla en
        # blanco, esconderlo.
        from rcm_runbook.export.rows import to_amef_rows

        s, _ = self._con_dos_tareas()
        texto = " ".join(str(v) for v in to_amef_rows(s)[0].model_dump().values())
        assert "Ver PLAN DE MANTENIMIENTO" in texto

    def test_con_una_sola_tarea_la_hoja_no_cambia(self):
        from rcm_runbook.export.rows import to_amef_rows

        s, fm = self._con_dos_tareas()
        s.tasks[fm] = s.tasks[fm][:1]
        texto = " ".join(str(v) for v in to_amef_rows(s)[0].model_dump().values())
        assert "Mensual" in texto and "Ver PLAN" not in texto


class TestElGlosarioLlegaAlModelo:
    """`ROUTE_LABELS_ES` arreglaba la salida de `run_decision_logic` pero nunca
    entraba en el contexto del modelo: preguntado a pelo —que es lo que hará el
    cliente al mirar la columna «Falla Evidente (ABCD)» de su Excel— cuatro
    corridas dieron tres alfabetos contradictorios, una de ellas re-asignando
    las siete letras a políticas de mantenimiento."""

    def _instrucciones(self) -> str:
        from rcm_runbook.agent.instructions_es import INSTRUCTIONS_ES

        return INSTRUCTIONS_ES

    def test_las_siete_letras_estan_en_las_instrucciones(self):
        from rcm_runbook.models.catalogs import ROUTE_LABELS_ES

        texto = self._instrucciones()
        for letra, significado in ROUTE_LABELS_ES.items():
            assert f"- {letra} — {significado}" in texto, f"la ruta {letra} no llega"

    def test_las_politicas_estan_en_las_instrucciones(self):
        from rcm_runbook.models.catalogs import POLICY_LABELS_ES

        texto = self._instrucciones()
        for politica, nombre in POLICY_LABELS_ES.items():
            assert f"- {politica.value} — {nombre}" in texto, f"{politica.value} no llega"

    def test_avisa_de_la_colision_de_la_A(self):
        # Una corrida racionalizó la colisión con «Parecen iguales pero no lo
        # son». Sí lo son, y hay que decirlo antes de que la explique.
        assert "AMBAS familias" in self._instrucciones()

    def test_explica_como_corregir_un_dato(self):
        texto = self._instrucciones()
        assert "reemplazar=True" in texto
        assert "record_task" in texto


class TestUnaCorreccionNoSeDescartaEnSilencio:
    """La familia entera. Revertir el arreglo de `add_failure_mode` —volver a
    `return existing`— dejaba las 344 en verde: el arreglo se documentó como
    corregido y no tenía ni un test. Estos cubren los tres mutadores."""

    def _sesion(self):
        from rcm_runbook.models.session import RCMSession

        s = RCMSession()
        s.add_function(kind="primaria", verb="bombear", object="crudo",
                       performance_standard="850 GPM a 150 psi")
        s.add_functional_failure("F-001", "No alcanza el caudal requerido")
        return s

    def _modo(self, s, **cambios):
        base = dict(
            description="Cavitación por NPSH por debajo del requerido",
            mechanism="Cavitación", iso_code="LOO",
            cause="Operación fuera de las condiciones de diseño",
            root_cause="Filtro de succión obstruido",
            failure_pattern="Aleatoria",
        )
        base.update(cambios)
        return s.add_failure_mode("FF-001", **base)

    def test_el_modo_con_otra_causa_no_se_traga_en_silencio(self):
        import pytest

        from rcm_runbook.errors import ReglaDeNegocio

        s = self._sesion()
        self._modo(s)
        with pytest.raises(ReglaDeNegocio, match="reemplazar=True"):
            self._modo(s, cause="Lubricante degradado por agua")
        assert s.failure_modes["FM-001"].cause.startswith("Operación fuera")

    def test_con_reemplazar_la_correccion_del_modo_se_aplica(self):
        s = self._sesion()
        self._modo(s)
        fm = self._modo(s, cause="Lubricante degradado por agua", reemplazar=True)
        assert fm.id == "FM-001" and len(s.failure_modes) == 1
        assert s.failure_modes["FM-001"].cause == "Lubricante degradado por agua"

    def test_un_reintento_que_omite_un_opcional_no_se_toma_por_correccion(self):
        # El diff comparaba el volcado entero: un reintento sin el argumento
        # opcional llegaba con el valor por defecto y se reportaba como
        # «cambia: cause, tpef» cuando nadie tocó el tpef.
        s = self._sesion()
        self._modo(s, tpef_hours=None)
        assert self._modo(s).id == "FM-001", "un reintento parcial disparó el rechazo"

    def test_la_tarea_se_puede_reemplazar_de_verdad(self):
        # El mensaje prometía «la reemplazo» y no había forma de hacerlo: una
        # tarea mal registrada era permanente.
        from rcm_runbook.models.domain import MaintenanceTask

        s = self._sesion()
        self._modo(s)
        base = dict(failure_mode_id="FM-001", discipline="Mecánico",
                    duration_hours=2.0, requires_shutdown=False)
        s.add_task(MaintenanceTask(description="Inspección de rodamientos",
                                   frequency="Mensual", **base))
        s.add_task(MaintenanceTask(description="Inspección de rodamientos",
                                   frequency="Semestral", **base), reemplazar=True)
        assert len(s.tasks["FM-001"]) == 1
        assert s.tasks["FM-001"][0].frequency == "Semestral"

    def test_confirmar_que_no_hay_funciones_primarias_no_es_un_no_op(self):
        # Devolvía «✔ Confirmado» sobre una rama que no existía.
        import pytest

        from rcm_runbook.errors import ReglaDeNegocio
        from rcm_runbook.models.domain import FunctionKind

        s = self._sesion()
        with pytest.raises(ReglaDeNegocio, match="siempre tiene función primaria"):
            s.confirm_no_functions_of_kind(FunctionKind.PRIMARIA)
