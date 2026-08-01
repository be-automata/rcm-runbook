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
    """Un módulo y su test, dentro del repo para que `uv run pytest` los vea.

    Con nombre propio por test: los cinco compartían `_arnes_tmp/`, así que dos
    corridas a la vez —la suite y el arnés, que es la situación normal cuando se
    mide— se pisaban y producían fallos que no eran de nadie. Costó un rato
    entender que el rojo era mío y no del código.
    """
    destino = RAIZ / "tests" / "unit" / f"_arnes_tmp_{tmp_path.name}"
    destino.mkdir(exist_ok=True)
    (destino / "__init__.py").write_text("")
    (destino / "modulo.py").write_text(cuerpo)
    # El import se escribe con el nombre real del directorio: con la ruta fija,
    # el módulo de juguete no se podía importar y la línea base salía roja por
    # una causa que nada tenía que ver con lo que se medía.
    (destino / "test_modulo.py").write_text(
        prueba.replace("_ARNES_", f"tests.unit.{destino.name}")
    )
    return destino / "modulo.py", destino / "test_modulo.py"


class TestElArnesNoFirmaLoQueNoMidio:
    MODULO = (
        "VALOR = 4  # un comentario cualquiera\n\n\n"
        "def doble() -> int:\n    return VALOR * 2\n"
    )
    PRUEBA = (
        "from _ARNES_.modulo import doble\n\n\n"
        "def test_doble():\n    assert doble() == 8\n"
    )

    def _limpiar(self, destino: Path) -> None:
        import shutil

        shutil.rmtree(destino.parent, ignore_errors=True)

    def _suite(self, destino: Path) -> str:
        return str((destino.parent / "test_modulo.py").relative_to(RAIZ))

    def test_con_la_linea_base_roja_no_mide_nada_y_lo_dice(self, tmp_path):
        # Suite roja por un motivo ajeno a la mutación.
        rota = self.PRUEBA.replace("== 8", "== 9")
        modulo, _ = _proyecto(tmp_path, self.MODULO, rota)
        try:
            r = _correr([{
                "nombre": "control inerte: cambia una letra de un COMENTARIO",
                "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "un comentario cualquiera", "despues": "un comentario cualquierx",
                "suite": self._suite(modulo),
            }], tmp_path)
        finally:
            self._limpiar(modulo)
        assert r.returncode == 2, f"firmó una medición imposible:\n{r.stdout}"
        assert "LÍNEA BASE ROJA" in r.stdout
        assert "MUERTO" not in r.stdout, "declaró muerto a un comentario"

    def test_una_corrida_que_no_ocurre_es_invalida_no_superviviente(self, tmp_path):
        """Devolvía VIVO: fabricaba un hueco de test que no existe.

        La suite tiene que EXISTIR y pasar en la línea base, y romperse solo al
        mutar. Si se apunta a una suite inexistente, aborta antes por línea base
        roja y el test pasa sin haber tocado nunca la rama del `returncode` —que
        es justo lo que se quiere fijar—. Aquí la mutación deja el módulo sin
        importar, así que pytest devuelve 2 (error de recolección), no 1.
        """
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        try:
            r = _correr([{
                "nombre": "la mutación impide recolectar la suite",
                "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "VALOR = 4",
                "despues": "import modulo_que_no_existe\n\nVALOR = 4",
                "suite": self._suite(modulo),
            }], tmp_path)
        finally:
            self._limpiar(modulo)
        assert "LÍNEA BASE ROJA" not in r.stdout, "abortó antes de medir"
        assert r.returncode == 2, f"contó como medición lo que no corrió:\n{r.stdout}"
        assert "VIVO" not in r.stdout and "MUERTO" not in r.stdout

    def test_un_mutante_de_verdad_muere_y_uno_inerte_sobrevive(self, tmp_path):
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        try:
            r = _correr([
                {"nombre": "rompe el cálculo", "fichero": str(modulo.relative_to(RAIZ)),
                 "antes": "VALOR * 2", "despues": "VALOR * 3",
                 "suite": self._suite(modulo)},
                {"nombre": "toca un comentario", "fichero": str(modulo.relative_to(RAIZ)),
                 "antes": "un comentario cualquiera", "despues": "otro comentario distinto",
                 "suite": self._suite(modulo)},
            ], tmp_path)
        finally:
            self._limpiar(modulo)
        assert "MUERTO  rompe el cálculo" in r.stdout
        assert "VIVO    toca un comentario" in r.stdout
        # Y el que se APUNTA como hueco tiene que ser el que sobrevivió: con la
        # lista de supervivientes construida al revés, las dos líneas de arriba
        # salen igual y el arnés señala al mutante equivocado.
        cola = r.stdout.split("sobreviven")[-1]
        assert "toca un comentario" in cola and "rompe el cálculo" not in cola
        assert r.returncode == 1, "un superviviente es un hueco, no un éxito"

    def test_un_tope_de_tiempo_agotado_no_pasa_por_medicion(self, tmp_path):
        """Un mutante puede colgar la suite, y hay dos maneras de mentir con eso.

        Sin tope, el arnés espera para siempre con el fichero mutado dentro del
        árbol. Y si al agotarse se devolviera 0, un tope agotado EN LA LÍNEA
        BASE se leería como verde y se firmaría una medición sobre una suite
        que nunca terminó. Las dos líneas se estrenaron sin un test.
        """
        import scripts.mutar as arnes

        lento = (
            "import time\n\n\ndef test_lento():\n    time.sleep(30)\n"
        )
        modulo, _ = _proyecto(tmp_path, self.MODULO, lento)
        try:
            codigo = arnes._correr(self._suite(modulo), tope=2)
        finally:
            self._limpiar(modulo)
        assert codigo not in (0, 1), (
            f"un tope agotado se contó como corrida válida: {codigo}"
        )

    def test_deja_el_fichero_como_estaba(self, tmp_path):
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        antes = modulo.read_text()
        try:
            _correr([{
                "nombre": "cualquiera", "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "VALOR * 2", "despues": "VALOR * 3",
                "suite": self._suite(modulo),
            }], tmp_path)
            assert modulo.read_text() == antes
        finally:
            self._limpiar(modulo)

    def test_una_mutacion_que_aplica_dos_veces_tampoco(self, tmp_path):
        # El tercer motivo del docstring de `mutar.py` —«el reemplazo que aplica
        # de más»— no tenía test: con dos coincidencias se muta más de lo que se
        # cree y el resultado no dice nada del sitio que se quería probar.
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        try:
            r = _correr([{
                "nombre": "dos coincidencias",
                "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "VALOR", "despues": "OTRO",
                "suite": self._suite(modulo),
            }], tmp_path)
        finally:
            self._limpiar(modulo)
        assert r.returncode == 2, f"midió con el reemplazo repetido:\n{r.stdout}"
        assert "2 coincidencias" in r.stdout

    def test_una_mutacion_que_no_aplica_no_se_cuenta_como_medida(self, tmp_path):
        modulo, _ = _proyecto(tmp_path, self.MODULO, self.PRUEBA)
        try:
            r = _correr([{
                "nombre": "no aparece en el fichero",
                "fichero": str(modulo.relative_to(RAIZ)),
                "antes": "esto no está", "despues": "da igual",
                "suite": self._suite(modulo),
            }], tmp_path)
        finally:
            self._limpiar(modulo)
        assert r.returncode == 2 and "INVÁLIDA" in r.stdout
