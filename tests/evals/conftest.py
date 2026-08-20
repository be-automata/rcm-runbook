"""Una corrida, un acta: la conversación se ejecuta UNA vez y la comparten todos.

Antes cada aserción vivía dentro del arnés y la primera en fallar ocultaba a las
demás, así que una corrida de veinte minutos producía un solo bit. Aquí la
conversación es una fixture de alcance sesión: se corre una vez, se persiste
entera, y cada test lee su criterio del acta.

Persistencia y replay
---------------------
Toda corrida se vuelca a disco (estado final, transcript completo y acta). Con
`--eval-session=<ruta.json>` la fixture recarga un volcado en vez de hablar con el
modelo, así que afinar los criterios, sus mensajes y su atribución **no cuesta
API**. Sin esto, cada hipótesis costaba veinte minutos y saldo.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from tests.evals.acta import CRITERIOS_CANONICOS, Estado
from tests.evals.stakeholder_sim import (
    AveriaDelInstrumento,
    ResultadoEval,
    load_scenario,
    run_llm_eval,
)


def pytest_addoption(parser: pytest.Parser) -> None:
    grupo = parser.getgroup("evals")
    grupo.addoption(
        "--eval-session",
        default=None,
        help="Ruta a un volcado de corrida previa: levanta el acta sin gastar API.",
    )
    grupo.addoption(
        "--eval-artifacts-dir",
        default=None,
        help="Dónde volcar estado, transcript y acta de la corrida (default: tmp).",
    )


@pytest.fixture(scope="session")
def sesion_guiada(request: pytest.FixtureRequest) -> ResultadoEval:
    """La conversación guiada, corrida una sola vez.

    Ante una avería del instrumento (429, presupuesto agotado, proveedor caído) el
    test da **error**, nunca `skip`: en una suite manual un `skip` es
    indistinguible de un verde, y un instrumento que acusa al producto de su
    propia avería es peor que no medir.
    """
    replay = request.config.getoption("--eval-session")
    if replay:
        datos = json.loads(Path(replay).read_text(encoding="utf-8"))
        return ResultadoEval.desde_json(datos, load_scenario())

    try:
        resultado = run_llm_eval()
    except AveriaDelInstrumento as exc:
        pytest.fail(f"EVAL NO EJECUTADO (avería del instrumento, no del producto): {exc}")

    _persistir(resultado, request.config.getoption("--eval-artifacts-dir"))
    return resultado


def _persistir(resultado: ResultadoEval, destino: str | None) -> None:
    """Siempre, pase o falle: una corrida sin volcado es información perdida."""
    import tempfile

    raiz = Path(destino) if destino else Path(tempfile.mkdtemp(prefix="rcm-eval-acta-"))
    raiz.mkdir(parents=True, exist_ok=True)
    # Sin marca de tiempo del reloj: el nombre lo dan los turnos y el motivo, que
    # es lo que sirve para elegir qué volcado releer.
    nombre = f"corrida-{resultado.turnos}t"
    (raiz / f"{nombre}.json").write_text(
        json.dumps(resultado.como_json(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (raiz / f"{nombre}-transcript.txt").write_text(
        "\n\n".join(resultado.transcript), encoding="utf-8"
    )
    (raiz / f"{nombre}-acta.txt").write_text(
        f"motivo de corte: {resultado.motivo_de_corte}\n"
        f"turnos: {resultado.turnos} · tokens: {resultado.tokens}\n\n"
        + resultado.acta().informe(),
        encoding="utf-8",
    )
    print(f"\n[eval] corrida volcada en {raiz}")
    if not destino:
        print(f"[eval] para reanalizarla sin gastar API: --eval-session={raiz / nombre}.json")


@pytest.fixture(scope="session")
def acta_guiada(sesion_guiada: ResultadoEval):
    """El acta de la corrida, con el censo ya comprobado.

    El censo va antes que cualquier veredicto: un criterio ausente es ROJO, no
    ausencia. Sin esto, un bug del arnés produciría una suite verde vacía — que es
    justo el fallo que `verificar_en_produccion.py` resume como «un obligatorio
    sin evaluar cuenta como fallo».
    """
    acta = sesion_guiada.acta()
    faltan = CRITERIOS_CANONICOS - set(acta.criterios)
    sobran = set(acta.criterios) - CRITERIOS_CANONICOS
    assert not faltan and not sobran, (
        f"el acta no cuadra con el censo canónico — faltan {sorted(faltan)}, "
        f"sobran {sorted(sobran)}"
    )
    if os.environ.get("RCM_EVAL_VERBOSE", "1") != "0":
        print(
            f"\n[eval] motivo de corte: {sesion_guiada.motivo_de_corte} · "
            f"{sesion_guiada.turnos} turnos · {sesion_guiada.tokens} tokens\n"
            + acta.informe()
        )
    return acta


def exige(acta, criterio_id: str) -> None:
    """Un obligatorio: verde pasa; rojo y `no evaluable` fallan.

    `NO_EVALUABLE` sobre un obligatorio es rojo. La excepción se concede por lista
    nominal (`CONDICIONADOS`) y nunca por defecto: si se tolerara en general, un
    arnés que dejara de observar algo se leería como aprobado.
    """
    c = acta[criterio_id]
    assert c.estado is Estado.VERDE, str(c)


def exige_condicionado(acta, criterio_id: str) -> None:
    """Un obligatorio cuya observación depende de que el simulador cumpla su guion.

    Rojo falla; `no evaluable` se salta con el motivo a la vista, que es la
    limitación conocida documentada — el mismo trato que el criterio [27] de
    `verificar_en_produccion.py`.
    """
    c = acta[criterio_id]
    if c.estado is Estado.NO_EVALUABLE:
        pytest.xfail(f"limitación conocida — {c.evidencia}")
    assert c.estado is Estado.VERDE, str(c)
