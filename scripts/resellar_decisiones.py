#!/usr/bin/env python
"""Re-sella el `input_hash` de las decisiones RCM ya guardadas con la fórmula nueva.

    uv run python scripts/resellar_decisiones.py estado.json [otro.json ...]

Migración de DATOS, no de esquema: no cambia la forma de `DecisionResult` ni
vuelve a ejecutar la lógica de decisión —hacerlo re-pediría las firmas HITL de
los modos de seguridad/ambiente—. Sólo recalcula un campo.

Por qué hace falta: `failure_mode_snapshot` sellaba la decisión incluyendo los
controles, que no son insumo de `decide(fm, effect, answers)`. Al partirlo en
`score_snapshot` (con controles) y `decision_snapshot` (sin), TODA decisión
guardada queda desfasada respecto de la fórmula nueva —también las que hoy están
frescas, porque su hash viejo sí llevaba los controles dentro—. O sea: se
re-sellan todas, no sólo las que hoy aparecen obsoletas.

El patrón es el de `scripts/mutar.py`: volcar el estado previo, aplicar, y
**releer del disco y comparar**. Su cabecera lo explica mejor que yo —«un
`str.replace` que no encuentra su texto no avisa: devuelve el original»—: un
script de transformación que no verifica lo que aplicó miente sobre su
resultado. Aquí lo que se verifica, después de releer el fichero escrito, es:

  · ninguna política cambió (policy, consequence_class, rutas, FFI, intervalo,
    justificación, provisional),
  · ninguna firma HITL se perdió (`hitl_confirmed_by` y el `hitl_ledger`),
  · ninguna valoración se tocó (su sello sigue llevando los controles),
  · y las decisiones quedaron con el sello canónico, comprobado sin la
    tolerancia que `stale_decisions()` aplica a los sellos heredados.

Correrlo dos veces no cambia nada la segunda: el sello es función del estado.

Y no es opcional, aunque desplegar sin correrlo ya no degrade nada: una decisión
que conserva su sello heredado conserva también la sobre-sensibilidad vieja —los
prefijos se reconstruyen con la fórmula de 12 campos—, así que editar la
`description` de un modo sigue marcando su decisión obsoleta hasta que se
normaliza. El arreglo del falso positivo llega a las decisiones ya guardadas
sólo después de esto.

Acepta el volcado de una `RCMSession` o el `session_state` de agno —el que
lleva la sesión bajo la clave "rcm"—. Devuelve 0 si todo cuadra, 1 si alguna
comprobación falla, 2 si el fichero no se puede leer o no valida como sesión
(en ese caso no se escribe nada).

Antes de tocar el fichero se guarda una copia entera como `<nombre>.antes.json`,
que sí se puede restaurar con un `cp`, y la escritura es atómica.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from rcm_runbook.models.session import RCMSession

SESSION_KEY = "rcm"

# Todo lo que un re-sellado NO puede tocar. `input_hash` es, por definición, el
# único campo que sí cambia.
CAMPOS_INTOCABLES = (
    "failure_mode_id",
    "policy",
    "consequence_class",
    "justification",
    "evident_route",
    "hidden_route",
    "provisional",
    "hitl_confirmed_by",
    "ffi_hours",
    "recommended_interval",
)


class NoParece(ValueError):
    """El fichero no contiene una sesión RCM reconocible."""


# Las tres formas en las que aparece el estado, de fuera hacia dentro. La
# primera es la que devuelve producción —`app.py:378` y la API de agno—, o sea
# JUSTO la que baja un operador para migrar. Reconocer sólo las otras dos hacía
# que el guion procesara un volcado de producción, no tocara nada, y lo
# celebrara con un ✔ y salida 0: el estado desenvuelto salía vacío, `resellar`
# no encontraba decisiones y la verificación confirmaba su propio no-op.
_ENVOLTURAS: tuple[tuple[str, ...], ...] = (
    ("session_data", "session_state", SESSION_KEY),
    (SESSION_KEY,),
    (),
)

# Claves que sólo tiene una sesión RCM. `RCMSession.model_validate({})` acepta
# el diccionario vacío porque todos sus campos tienen valor por defecto, así que
# validar no distingue «sesión sin decisiones» de «esto no es una sesión». Sin
# este centinela, cualquier JSON pasa por el guion sin ruido.
_SENAS = ("schema_version", "failure_modes", "decisions")


def _estado(bruto: dict[str, Any]) -> dict[str, Any]:
    """La sesión dentro del fichero, sea cual sea la envoltura que la traiga.

    Devuelve una REFERENCIA al diccionario anidado, no una copia: `resellar`
    muta en el sitio y luego se escribe `bruto` entero, así que la envoltura se
    conserva tal cual venía.
    """
    for camino in _ENVOLTURAS:
        nodo: Any = bruto
        for clave in camino:
            if not isinstance(nodo, dict) or clave not in nodo:
                nodo = None
                break
            nodo = nodo[clave]
        if isinstance(nodo, dict) and any(s in nodo for s in _SENAS):
            return nodo
    raise NoParece(
        "no encontré una sesión RCM. Formas que entiendo: "
        "{'session_data': {'session_state': {'rcm': …}}} (lo que devuelve "
        "producción), {'rcm': …}, o el estado directo."
    )


def _sellos(estado: dict[str, Any], clave: str) -> dict[str, str]:
    """Los `input_hash` de una colección de valoraciones, por id."""
    return {fmid: s.get("input_hash", "") for fmid, s in estado.get(clave, {}).items()}


def volcado(estado: dict[str, Any]) -> dict[str, Any]:
    """Foto del estado previo: las decisiones enteras, las firmas y los sellos de
    valoración. Es contra esto que se compara lo releído."""
    return {
        "decisions": json.loads(json.dumps(estado.get("decisions", {}))),
        "hitl_ledger": json.loads(json.dumps(estado.get("hitl_ledger", []))),
        "risk_scores": _sellos(estado, "risk_scores"),
        "residual_scores": _sellos(estado, "residual_scores"),
    }


def resellar(estado: dict[str, Any]) -> list[str]:
    """Reescribe `input_hash` de cada decisión in situ. Devuelve los ids cambiados.

    Muta el dict bruto y no un `model_dump()` nuevo a propósito: así no hay forma
    de que un campo ajeno cambie de camino por un valor por defecto del modelo.
    """
    sesion = RCMSession.model_validate(estado)
    cambiados = []
    for fmid, decision in estado.get("decisions", {}).items():
        if fmid not in sesion.failure_modes:
            continue
        nuevo = sesion.decision_snapshot(fmid)
        if decision.get("input_hash") != nuevo:
            decision["input_hash"] = nuevo
            cambiados.append(fmid)
    return sorted(cambiados)


def _comparar(previo: dict[str, Any], estado: dict[str, Any]) -> list[str]:
    """Qué se rompió entre el volcado previo y lo releído del disco."""
    fallos = []
    decisiones = estado.get("decisions", {})
    if set(decisiones) != set(previo["decisions"]):
        fallos.append(
            f"cambió el conjunto de decisiones: antes {len(previo['decisions'])}, "
            f"ahora {len(decisiones)}"
        )
    for fmid, antes in previo["decisions"].items():
        ahora = decisiones.get(fmid)
        if ahora is None:
            fallos.append(f"{fmid}: la decisión desapareció")
            continue
        for campo in CAMPOS_INTOCABLES:
            if antes.get(campo) != ahora.get(campo):
                fallos.append(
                    f"{fmid}: cambió '{campo}': {antes.get(campo)!r} → {ahora.get(campo)!r}"
                )
        if set(antes) != set(ahora):
            fallos.append(f"{fmid}: cambió el conjunto de campos de la decisión")
    if previo["hitl_ledger"] != estado.get("hitl_ledger", []):
        fallos.append("cambió el hitl_ledger")
    for clave in ("risk_scores", "residual_scores"):
        if _sellos(estado, clave) != previo[clave]:
            fallos.append(f"cambió algún sello de {clave}")
    sesion = RCMSession.model_validate(estado)
    # ESTRICTO a propósito, y NO `stale_decisions()`: esa acepta los sellos de
    # fórmulas anteriores para que desplegar no degrade el estado vivo, así que
    # daría por bueno un fichero en el que este guion no aplicó nada. El trabajo
    # de este guion es justamente normalizar al sello canónico, de modo que la
    # compatibilidad se pueda retirar; su verificación tiene que exigir la
    # igualdad exacta, no la tolerancia.
    sin_normalizar = sesion.decisiones_sin_sello_canonico()
    if sin_normalizar:
        fallos.append(
            f"siguen sin el sello canónico {len(sin_normalizar)} decisiones: "
            f"{', '.join(sin_normalizar)}"
        )
    return fallos


def procesar(ruta: Path) -> int:
    try:
        bruto = json.loads(ruta.read_text("utf-8"))
        estado = _estado(bruto)
        previo = volcado(estado)
        # El re-sellado se calcula ANTES de escribir nada: si el estado no valida
        # como `RCMSession`, el fichero original queda intacto. Que ese orden se
        # mantenga no es cosmético — es lo único que impide dejar un estado a
        # medio migrar.
        cambiados = resellar(estado)
    except (OSError, ValueError, ValidationError) as exc:
        print(f"  ✗ no se pudo leer {ruta}: {type(exc).__name__}: {exc}")
        print("  El fichero no se tocó.")
        return 2

    # Copia ENTERA del fichero original, no el volcado de las decisiones: un
    # `.antes.json` parcial no se puede restaurar, y el mensaje de error decía
    # que sí. Y no se pisa: correr el script dos veces borraría el único
    # registro del estado previo dejando en su lugar el ya migrado.
    destino = ruta.parent / f"{ruta.stem}.antes.json"
    if destino.exists():
        print(f"  volcado previo: {destino} ya existe, se conserva el de la primera corrida")
    else:
        shutil.copy2(ruta, destino)
        print(f"  volcado previo → {destino} ({len(previo['decisions'])} decisiones)")

    # Escritura atómica: un corte a media escritura dejaría el estado truncado.
    temporal = ruta.with_suffix(ruta.suffix + ".tmp")
    temporal.write_text(json.dumps(bruto, ensure_ascii=False, indent=1), "utf-8")
    os.replace(temporal, ruta)
    print(f"  re-selladas {len(cambiados)} de {len(previo['decisions'])}: "
          f"{', '.join(cambiados) or 'ninguna (ya estaban al día)'}")

    # Releer del disco: lo que se comprueba es el fichero, no la variable que
    # creemos haber escrito.
    releido = _estado(json.loads(ruta.read_text("utf-8")))
    fallos = _comparar(previo, releido)
    for fallo in fallos:
        print(f"  ✗ {fallo}")
    if fallos:
        print(f"  {ruta}: {len(fallos)} comprobaciones fallaron. El fichero YA está escrito: "
              f"restaure con `cp {destino} {ruta}`.")
        return 1
    firmadas = sum(1 for d in releido.get("decisions", {}).values() if d.get("hitl_confirmed_by"))
    print(f"  ✔ {ruta.name}: ninguna política cambió, {firmadas} firmas HITL intactas, "
          "0 decisiones obsoletas.")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    peor = 0
    for arg in argv[1:]:
        ruta = Path(arg)
        if not ruta.is_file():
            print(f"  ✗ no existe: {ruta}")
            peor = max(peor, 2)
            continue
        print(f"{ruta}:")
        peor = max(peor, procesar(ruta))
    return peor


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
