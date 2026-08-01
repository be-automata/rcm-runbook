"""El arnés de mutación también se prueba: si miente, miente sobre todo lo demás.

El validador lo desmontó con tres casos y los tres están aquí. El peor no era
que se equivocara: era que se equivocaba EN VERDE. Con la suite ya roja por un
motivo ajeno, una mutación que solo cambiaba una letra dentro de un comentario
salía «MUERTO» y el arnés firmaba 0. Un comentario no puede matar a nadie.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
MUTAR = RAIZ / "scripts" / "mutar.py"


def _correr(mutaciones: list[dict], tmp_path: Path) -> subprocess.CompletedProcess:
    fichero = tmp_path / "mut.json"
    fichero.write_text(json.dumps(mutaciones))
    return subprocess.run(
        [sys.executable, str(MUTAR), str(fichero)],
        capture_output=True, text=True, cwd=RAIZ,
    )


def _proyecto(tmp_path: Path, cuerpo: str, prueba: str) -> tuple[Path, Path]:
    """Un módulo y su test, dentro del repo para que `uv run pytest` los vea."""
    destino = RAIZ / "tests" / "unit" / "_arnes_tmp"
    destino.mkdir(exist_ok=True)
    (destino / "__init__.py").write_text("")
    (destino / "modulo.py").write_text(cuerpo)
    (destino / "test_modulo.py").write_text(prueba)
    return destino / "modulo.py", destino / "test_modulo.py"


class TestElArnesNoFirmaLoQueNoMidio:
    MODULO = (
        "VALOR = 4  # un comentario cualquiera\n\n\n"
        "def doble() -> int:\n    return VALOR * 2\n"
    )
    PRUEBA = (
        "from tests.unit._arnes_tmp.modulo import doble\n\n\n"
        "def test_doble():\n    assert doble() == 8\n"
    )

    def _limpiar(self) -> None:
        import shutil

        shutil.rmtree(RAIZ / "tests" / "unit" / "_arnes_tmp", ignore_errors=True)

    def test_con_la_linea_base_roja_no_mide_nada_y_lo_dice(self, tmp_path):
        # Suite roja por un motivo ajeno a la mutación.
        rota = self.PRUEBA.replace("== 8", "== 9")
        modulo, _ = _proyecto(tmp_path, self.MODULO, rota)
        try:
            r = _correr([{
                "nombre": "control inerte: cambia una letra de un COMENTARIO",
                "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "un comentario cualquiera", "despues": "un comentario cualquierx",
                "suite": "tests/unit/_arnes_tmp/test_modulo.py",
            }], tmp_path)
        finally:
            self._limpiar()
        assert r.returncode == 2, f"firmó una medición imposible:\n{r.stdout}"
        assert "LÍNEA BASE ROJA" in r.stdout
        assert "MUERTO" not in r.stdout, "declaró muerto a un comentario"

    def test_una_suite_que_no_existe_es_invalida_no_superviviente(self, tmp_path):
        # Devolvía VIVO: fabricaba un hueco de test que no existe.
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        try:
            r = _correr([{
                "nombre": "la suite apuntada no existe",
                "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "VALOR * 2", "despues": "VALOR * 3",
                "suite": "tests/unit/no_existe_esta_suite.py",
            }], tmp_path)
        finally:
            self._limpiar()
        assert r.returncode == 2, f"contó como medición lo que no corrió:\n{r.stdout}"
        assert "VIVO" not in r.stdout

    def test_un_mutante_de_verdad_muere_y_uno_inerte_sobrevive(self, tmp_path):
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        try:
            r = _correr([
                {"nombre": "rompe el cálculo", "fichero": str(modulo.relative_to(RAIZ)),
                 "antes": "VALOR * 2", "despues": "VALOR * 3",
                 "suite": "tests/unit/_arnes_tmp/test_modulo.py"},
                {"nombre": "toca un comentario", "fichero": str(modulo.relative_to(RAIZ)),
                 "antes": "un comentario cualquiera", "despues": "otro comentario distinto",
                 "suite": "tests/unit/_arnes_tmp/test_modulo.py"},
            ], tmp_path)
        finally:
            self._limpiar()
        assert "MUERTO  rompe el cálculo" in r.stdout
        assert "VIVO    toca un comentario" in r.stdout
        assert r.returncode == 1, "un superviviente es un hueco, no un éxito"

    def test_deja_el_fichero_como_estaba(self, tmp_path):
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        antes = modulo.read_text()
        try:
            _correr([{
                "nombre": "cualquiera", "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "VALOR * 2", "despues": "VALOR * 3",
                "suite": "tests/unit/_arnes_tmp/test_modulo.py",
            }], tmp_path)
            assert modulo.read_text() == antes
        finally:
            self._limpiar()

    def test_una_mutacion_que_no_aplica_no_se_cuenta_como_medida(self, tmp_path):
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        try:
            r = _correr([{
                "nombre": "no aparece en el fichero",
                "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "esto no está", "despues": "da igual",
                "suite": "tests/unit/_arnes_tmp/test_modulo.py",
            }], tmp_path)
        finally:
            self._limpiar()
        assert r.returncode == 2 and "INVÁLIDA" in r.stdout
