"""Fixtures compartidas de las pruebas unitarias.

`client` y `con_llave` vivían duplicadas por archivo, y eso dejaba las pruebas
de cierre de la API saltándose *en verde* en cualquier entorno sin `.env`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from rcm_runbook.config import settings

LLAVE_DE_PRUEBA = "llave-de-prueba"


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
