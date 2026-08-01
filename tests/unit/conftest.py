"""Fixtures compartidas de las pruebas unitarias.

`client` y `con_llave` vivían duplicadas por archivo, y eso dejaba las pruebas
de cierre de la API saltándose *en verde* en cualquier entorno sin `.env`.
"""

from __future__ import annotations

import os

LLAVE_DE_PRUEBA = "llave-de-prueba"

# Credenciales de mentira ANTES de importar nada de rcm_runbook, y solo si el
# entorno no trae unas de verdad.
#
# `app.py` hace SystemExit sin credencial del proveedor —correcto en producción,
# porque arrancar sin ella regala un error en el primer mensaje del chat—, pero
# eso dejaba 61 pruebas sin poder ejecutarse en un entorno limpio: el cierre de
# la API, las rutas de export, la página de demo y la sonda solo existían en la
# máquina del desarrollador. Ninguna llama al modelo; solo necesitan importar.
#
# La llave de acceso va por lo mismo: agno la captura al importar, así que
# `con_llave` (que parchea nuestros settings) no alcanzaba a las cuatro pruebas
# del WebSocket y se saltaban en verde justo donde se comprueba que el socket
# exige autenticación.
#
# `setdefault` no vale: en CI la variable suele estar presente y vacía.
if not os.environ.get("ANTHROPIC_API_KEY") and not os.environ.get(
    "CLAUDE_CODE_OAUTH_TOKEN"
):
    os.environ["ANTHROPIC_API_KEY"] = "sk-ant-de-mentira-para-pruebas"
# RCM_OS_SECURITY_KEY y NO OS_SECURITY_KEY: ese segundo nombre lo lee también el
# AgnoAPISettings por defecto, que activa su propia dependencia de auth —solo
# acepta `Authorization: Bearer`— y mata los enlaces `?key=`. Es un defecto que
# ya llegó a producción, y al ponerlo aquí lo reintroduje: lo cazó
# `test_browser_links_accept_key_query_param`, que existe justo para eso.
if not os.environ.get("OS_SECURITY_KEY") and not os.environ.get(
    "RCM_OS_SECURITY_KEY"
):
    os.environ["RCM_OS_SECURITY_KEY"] = LLAVE_DE_PRUEBA

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from rcm_runbook.config import settings  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory) -> TestClient:
    """App real, con exports y base de datos en directorios temporales."""
    from rcm_runbook import app as app_module

    exports = tmp_path_factory.mktemp("exports")
    settings.exports_dir = str(exports)
    settings.db_path = str(tmp_path_factory.mktemp("db") / "test.db")
    app_module.settings.exports_dir = str(exports)
    return TestClient(app_module.app)


@pytest.fixture
def con_llave(monkeypatch) -> str:
    """Fuerza una llave configurada.

    Sin esto las pruebas de seguridad se saltaban en verde cuando no había
    `.env`: en un entorno limpio nadie se enteraría de que la API quedó abierta.
    """
    from rcm_runbook import app as app_module

    monkeypatch.setattr(settings, "os_security_key", LLAVE_DE_PRUEBA)
    monkeypatch.setattr(app_module.settings, "os_security_key", LLAVE_DE_PRUEBA)
    return LLAVE_DE_PRUEBA
