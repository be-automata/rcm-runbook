"""Eval harness: stakeholder simulator vs. RCM facilitator.

Two entry points:
- run_scripted_eval()  — NO LLM: drives the facilitator's tools directly from the
  YAML ground-truth scenario (same pattern as tests/unit/test_tools.py) and returns
  the final RCMSession. Validates the scenario is complete and all gates go green.
- run_llm_eval()       — LLM-vs-LLM: the real facilitator agent (build_agent) talks
  to a second Agno agent that role-plays maintenance engineer "Carlos", answering
  STRICTLY from the YAML ground truth and firing scripted adversarial probes.
  MIDE y no juzga: devuelve un `ResultadoEval` del que se levanta un acta con un
  veredicto por criterio (ver `tests/evals/acta.py`). Nunca lanza por un fallo del
  producto — sólo `AveriaDelInstrumento` cuando el eval no pudo medir.

El guionizado sí lanza `AssertionError`: sin modelo de por medio no hay
estocasticidad que tolerar, así que un fallo es un fallo.

Regla que gobierna los dos caminos: se mide el ESTADO y las llamadas a
herramienta, nunca la prosa. El agente parafrasea, y una comprobación sobre lo que
dice mide su redacción, no su trabajo.
"""

from __future__ import annotations

import os
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from rcm_runbook.agent import tools as t
from rcm_runbook.engine import compliance
from rcm_runbook.export.excel import PREFIJO_BORRADOR, PREFIJO_DEFINITIVO, export_xlsx
from rcm_runbook.models.session import RCMSession
from tests.evals.acta import Acta, levantar_acta

SCENARIO_PATH = Path(__file__).parent / "scenarios" / "pump_p101.yaml"


def load_scenario(path: Path = SCENARIO_PATH) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Scripted eval — no LLM, tools driven directly from the ground truth
# ---------------------------------------------------------------------------


@dataclass
class FakeRunContext:
    session_state: dict[str, Any] = field(default_factory=dict)
    session_id: str = "eval-scripted"


def _call(tool_obj: Any, ctx: FakeRunContext, **kwargs: Any) -> str:
    """Invoke the underlying entrypoint of an agno @tool."""
    fn = getattr(tool_obj, "entrypoint", tool_obj)
    return fn(run_context=ctx, **kwargs)


def _expect(condition: bool, message_es: str, output: str = "") -> None:
    if not condition:
        detail = f"\nSalida de la herramienta:\n{output}" if output else ""
        raise AssertionError(f"EVAL FALLIDO — {message_es}{detail}")


def _mode_kwargs(fm: dict[str, Any]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "functional_failure_id": fm["functional_failure_ref"],
        "description": fm["description"],
        "mechanism": fm["mechanism"],
        "iso_code": fm["iso_code"],
        "cause": fm["cause"],
        "root_cause": fm["root_cause"],
        "failure_pattern": fm["failure_pattern"],
        "credible": fm.get("credible", True),
        "non_credible_discard": fm.get("non_credible_discard", ""),
    }
    if fm.get("pf_interval_hours"):
        kwargs["pf_interval_hours"] = fm["pf_interval_hours"]
    tpef = fm.get("tpef")
    if tpef:
        kwargs["tpef_hours"] = tpef["hours"]
        kwargs["tpef_fuente"] = tpef["fuente"]
        kwargs["tpef_note"] = tpef.get("note", "")
    return kwargs


def _scripted_probes(ctx: FakeRunContext, scenario: dict[str, Any]) -> None:
    """Deterministic slice of the adversarial probes: the tool layer itself must
    reject vague standards, cause==mode, maintenance-assumption effects and OHF
    on the hidden safety mode (the LLM-facing probes live in run_llm_eval)."""
    out = _call(t.record_function, ctx, kind="primaria", verb="bombear",
                object="crudo", performance_standard="bien")
    _expect(out.startswith("❌"), "el estándar vago 'bien' debió rechazarse", out)

    fm1 = scenario["failure_modes"][0]
    out = _call(t.record_failure_mode, ctx, **{
        **_mode_kwargs(fm1), "cause": fm1["description"],
    })
    _expect(out.startswith("❌"),
            "una causa que reformula el modo de falla debió rechazarse", out)

    out = _call(t.record_effect, ctx, failure_mode_id="FM-001",
                local="No pasa nada porque la inspección lo detecta antes",
                system="Sin impacto real en el sistema",
                plant="Ninguno", is_hidden=False, operational=True)
    _expect(out.startswith("❌"),
            "un efecto con supuesto de mantenimiento debió rechazarse", out)


def run_scripted_eval(exports_dir: str | None = None) -> RCMSession:
    """Drive all six phases through the real tool entrypoints from the YAML ground
    truth. Returns the final RCMSession with every gate green and export done."""
    scenario = load_scenario()
    ctx = FakeRunContext()
    previous_exports_dir = t.settings.exports_dir
    if exports_dir:
        t.settings.exports_dir = exports_dir
    try:
        # Probe: export prematuro debe rechazarse con la lista de faltantes
        out = _call(t.export_excel, ctx)
        _expect(out.startswith("❌") and "Fase 1" in out,
                "el export prematuro debió rechazarse listando faltantes", out)

        # --- P1: alcance y equipo ---
        out = _call(t.record_scope, ctx, **scenario["scope"])
        _expect("Alcance completo" in out, "el alcance del escenario está incompleto", out)
        for member in scenario["team"]:
            _call(t.record_team_member, ctx, name=member["name"], role=member["role"])
        out = _call(t.advance_phase, ctx)
        _expect("fase 2" in out, "la compuerta P1 no quedó en verde", out)

        # --- P2: funciones y fallas funcionales ---
        for fn in scenario["functions"]:
            out = _call(t.record_function, ctx, kind=fn["kind"], verb=fn["verb"],
                        object=fn["object"], performance_standard=fn["performance_standard"])
            _expect(fn["ref"] in out, f"la función {fn['ref']} no se registró", out)
        if scenario.get("no_secondary_functions"):
            _call(t.confirm_no_functions, ctx, kind="secundaria")
        for ff in scenario["functional_failures"]:
            out = _call(t.record_functional_failure, ctx,
                        function_id=ff["function_ref"], description=ff["description"])
            _expect(ff["ref"] in out, f"la falla funcional {ff['ref']} no se registró", out)
        out = _call(t.advance_phase, ctx)
        _expect("fase 3" in out, "la compuerta P2 no quedó en verde", out)

        # --- P3: AMEF ---
        for fm in scenario["failure_modes"]:
            out = _call(t.record_failure_mode, ctx, **_mode_kwargs(fm))
            _expect(fm["ref"] in out, f"el modo {fm['ref']} no se registró", out)
        _scripted_probes(ctx, scenario)
        for effect in scenario["effects"]:
            out = _call(t.record_effect, ctx,
                        failure_mode_id=effect["failure_mode_ref"],
                        local=effect["local"], system=effect["system"],
                        plant=effect["plant"], is_hidden=effect["is_hidden"],
                        safety=effect.get("safety", False),
                        environment=effect.get("environment", False),
                        operational=effect.get("operational", False),
                        non_operational=effect.get("non_operational", False))
            _expect(out.startswith("✔"),
                    f"los efectos de {effect['failure_mode_ref']} no se registraron", out)
        for control in scenario["controls"]:
            _call(t.record_control, ctx, failure_mode_id=control["failure_mode_ref"],
                  kind=control["kind"], description=control["description"])
        out = _call(t.advance_phase, ctx)
        _expect("fase 4" in out, "la compuerta P3 no quedó en verde", out)

        # --- P4: riesgo S/O/D ---
        for score in scenario["risk_scores"]:
            out = _call(t.score_risk, ctx, failure_mode_id=score["failure_mode_ref"],
                        severity=score["severity"], occurrence=score["occurrence"],
                        detection=score["detection"])
            _expect(out.startswith("✔"),
                    f"la valoración de {score['failure_mode_ref']} falló", out)
        out = _call(t.advance_phase, ctx)
        _expect("fase 5" in out, "la compuerta P4 no quedó en verde", out)

        # --- P5: decisión RCM (con HITL para el modo oculto de seguridad) ---
        for decision in scenario["decisions"]:
            fmid = decision["failure_mode_ref"]
            answers = decision.get("answers", {})
            approver = decision.get("approver", "")
            if approver:
                # Probe OHF: intentar 'operar hasta la falla' en el modo de seguridad
                out = _call(t.run_decision_logic, ctx, failure_mode_id=fmid,
                            consequences_tolerable=True)
                _expect("CONFIRMACIÓN HUMANA" in out,
                        f"el modo de seguridad {fmid} debió exigir confirmación humana", out)
                out = _call(t.run_decision_logic, ctx, failure_mode_id=fmid,
                            **answers, approver=approver)
            else:
                out = _call(t.run_decision_logic, ctx, failure_mode_id=fmid, **answers)
            expected = decision["expected_policy"]
            _expect(f"Decisión de {fmid}: {expected}" in out,
                    f"la política de {fmid} debió ser {expected}", out)
        ffi = scenario.get("ffi")
        if ffi:
            # El escenario ya declaraba `failure_mode_ref` y el simulador no lo
            # pasaba: el FFI se calculaba y no quedaba atado a ningún modo, que
            # es justo cómo desaparecía del entregable.
            out = _call(t.calculate_ffi, ctx, method=ffi["method"],
                        mtive_hours=ffi["mtive_hours"], mted_hours=ffi["mted_hours"],
                        mmf_hours=ffi["mmf_hours"],
                        failure_mode_id=ffi["failure_mode_ref"])
            _expect("FFI" in out and out.startswith("✔"), "el cálculo de FFI falló", out)
            _expect("sale en el entregable" in out,
                    "el FFI se calculó pero no quedó registrado", out)
        for action in scenario["actions"]:
            _call(t.record_action, ctx, failure_mode_id=action["failure_mode_ref"],
                  what=action["what"], who=action["who"], when=action["when"],
                  verification=action["verification"],
                  resources=action.get("resources", ""))
        out = _call(t.advance_phase, ctx)
        _expect("fase 6" in out, "la compuerta P5 no quedó en verde", out)

        # --- P6: plan, gobernanza y export ---
        for task in scenario["tasks"]:
            _call(t.record_task, ctx, failure_mode_id=task["failure_mode_ref"],
                  description=task["description"], frequency=task["frequency"],
                  duration_hours=task["duration_hours"], discipline=task["discipline"],
                  requires_shutdown=task.get("requires_shutdown", False),
                  es_busqueda_de_fallas=task.get("es_busqueda_de_fallas", False))
        gov = scenario["governance"]
        _call(t.record_governance, ctx, kpis=gov["kpis"],
              review_triggers=gov["review_triggers"],
              validation_signoff=gov["validation_signoff"])

        out = _call(t.export_excel, ctx)
        _expect("✔ Entregable definitivo exportado" in out,
                "el export definitivo debió tener éxito con las compuertas en verde", out)

        session = RCMSession.model_validate(ctx.session_state[t.SESSION_KEY])
        _assert_final_state(session, scenario)
        return session
    finally:
        t.settings.exports_dir = previous_exports_dir


# ---------------------------------------------------------------------------
# Final-state assertions (shared by scripted and LLM evals)
# ---------------------------------------------------------------------------


def _assert_final_state(session: RCMSession, scenario: dict[str, Any]) -> None:
    """Envoltura que LANZA, para el eval guionizado (su contrato no cambia).

    El camino LLM no pasa por aquí: levanta el acta y deja que cada test juzgue su
    criterio. Aquí, en cambio, no hay estocasticidad —las herramientas se conducen
    desde el YAML— así que un fallo es un fallo y abortar es lo correcto.
    """
    failures: list[str] = []

    blockers = compliance.export_blockers(session)
    if blockers:
        failures.append(
            "Compuertas con faltantes (deben estar TODAS en verde):\n  - "
            + "\n  - ".join(blockers[:12])
        )

    credible = [fm for fm in session.failure_modes.values() if fm.credible]
    if len(credible) < 3:
        failures.append(f"Se esperaban ≥3 modos de falla creíbles; hay {len(credible)}.")

    discarded = [fm for fm in session.failure_modes.values() if not fm.credible]
    if not any(fm.non_credible_discard.strip() for fm in discarded):
        failures.append("Falta el modo no creíble con su descarte documentado.")

    hidden_bf = [
        fmid
        for fmid, d in session.decisions.items()
        if (e := session.effects.get(fmid)) is not None
        and e.is_hidden
        and d.policy.value == "BF"
        and d.hitl_confirmed_by
    ]
    if not hidden_bf:
        failures.append(
            "Falta al menos un modo OCULTO con decisión BF y confirmación humana "
            "(hitl_confirmed_by) registrada."
        )

    from collections import Counter

    expected_policies = Counter(d["expected_policy"] for d in scenario["decisions"])
    actual_policies = Counter(
        d.policy.value for fmid, d in session.decisions.items()
        if session.failure_modes[fmid].credible
    )
    missing = expected_policies - actual_policies
    if missing:
        failures.append(
            "Faltan políticas del escenario (los modos extra bien formados se toleran): "
            f"faltantes {dict(missing)}, obtenidas {dict(actual_policies)}."
        )

    audit = compliance.validate_ja1011(session)
    if audit:
        failures.append("Advertencias JA1011 (deben ser cero): " + "; ".join(audit))

    if failures:
        raise AssertionError(
            "EVAL FALLIDO — el estado final de la sesión no cumple el escenario:\n"
            + "\n".join(f"• {f}" for f in failures)
        )


# ---------------------------------------------------------------------------
# LLM-vs-LLM eval — simulator "Carlos" answers strictly from the ground truth
# ---------------------------------------------------------------------------

SIMULATOR_PROMPT_ES = """
Eres **Carlos Mendoza**, ingeniero de mantenimiento mecánico rotativo. Participas en
una entrevista RCM facilitada por un agente. Respondes SIEMPRE en español y
ESTRICTAMENTE con los datos del escenario de verdad-terreno de abajo — NUNCA inventes
datos que no estén allí. Si el facilitador pregunta algo que el escenario no cubre,
responde "no lo sé" o "no aplica".

Reglas de rol:
- Responde UNA pregunta a la vez, en MENOS DE 80 PALABRAS, sin monólogos ni listas
  largas — como en una reunión de planta con poco tiempo.
- PROHIBIDO inventar equipos, modos de falla, funciones o historias que no estén en
  el YAML (nada de rodamientos, acoples ni otros equipos si el escenario no los trae).
- Si el facilitador propone registrar algo que NO está en el escenario, di
  "eso no aplica a esta bomba" y reconduce al dato del YAML.
- Empuja a CERRAR: cuando el facilitador resuma o dude, pídele avanzar a la siguiente
  fase; el objetivo es llegar al entregable definitivo.
- OBLIGATORIO: cuando el facilitador pida modos de falla, menciona TODOS los del
  escenario, incluido el modo con `credible: false` — propónlo como posible modo y,
  si el facilitador evalúa su credibilidad, dale la justificación textual de
  `non_credible_discard` para que quede descartado y documentado.
- María Torres (supervisora de operaciones) está contigo; cuando el facilitador pida
  una confirmación humana por seguridad/ambiente, entrega el aval exacto del campo
  `approver` del escenario.
- Lanza cada sonda de la sección `adversarial_probes` UNA sola vez, en la fase que
  indica su campo `phase`, usando su `utterance` textual. Cuando el facilitador te
  corrija, acepta la corrección y entrega el dato correcto del escenario.
- No adelantes fases ni entregues datos que no te hayan pedido. No hagas tú de
  facilitador.
- Cuando el facilitador confirme que el entregable definitivo fue exportado, responde
  exactamente: FIN DE SESION

Escenario de verdad-terreno (YAML):
```yaml
{scenario_yaml}
```
"""

_SIM_DONE_MARKER = "FIN DE SESION"


def _tail(transcript: list[str], n: int = 8) -> str:
    """Últimos turnos de la conversación — diagnóstico cuando el eval falla."""
    return "Últimos turnos:\n" + "\n".join(transcript[-n:]) if transcript else ""


class AveriaDelInstrumento(RuntimeError):
    """El eval no pudo medir — no es que el producto fallara.

    429 tras el backoff, presupuesto agotado, proveedor caído. Se distingue del
    fallo del producto porque un instrumento que acusa al producto de su propia
    avería es peor que no medir.
    """


# Backoff ante saturación (la ventana se recupera sola): hasta ~25 min en total.
_BACKOFF_SCHEDULE_S = (60, 120, 240, 480, 600)

#: Sólo estos se reintentan: pasan solos. Un saldo agotado no.
_SATURACION = ("rate_limit_error", "Error code: 429", "overloaded_error")


def _averia_del_proveedor(output: Any) -> str:
    """Qué le pasa al proveedor, leído del contenido del turno. Cadena vacía = nada.

    agno captura el error del proveedor y lo devuelve como CONTENIDO del turno,
    no como excepción, así que se detecta leyendo. La clasificación se reusa de
    `app._FALLOS_DEL_PROVEEDOR`, que ya distingue saldo de saturación para
    hablarle al cliente: tener dos listas de patrones es cómo se llega a que el
    producto reconozca una avería y el instrumento no —que es exactamente lo que
    pasó—.
    """
    from rcm_runbook.app import _FALLOS_DEL_PROVEEDOR

    contenido = str(getattr(output, "content", "") or "")
    for patron, _mensaje in _FALLOS_DEL_PROVEEDOR:
        if patron.search(contenido):
            return patron.pattern
    return ""


def _es_saturacion(output: Any) -> bool:
    """¿Es de las que se arreglan esperando?"""
    contenido = str(getattr(output, "content", "") or "")
    return any(m in contenido for m in _SATURACION)


def _run_with_backoff(agent: Any, message: str, session_id: str) -> Any:
    """Ejecuta un turno; ante 429 espera y REINTENTA el mismo turno (no lo consume).

    agno captura el error del proveedor y lo devuelve como contenido del RunOutput,
    así que se detecta por contenido, no por excepción. Si la ventana de la
    suscripción no se recupera tras el backoff completo, aborta con un mensaje claro
    en vez de quemar turnos conversando con errores.
    """
    out = agent.run(message, session_id=session_id)
    averia = _averia_del_proveedor(out)
    if not averia:
        return out
    if not _es_saturacion(out):
        # Saldo agotado, credenciales inválidas: esperar no arregla ninguna, y
        # quemar 80 turnos contra un error convierte siete criterios en rojo
        # contra el facilitador por algo que no hizo. Se aborta de inmediato.
        raise AveriaDelInstrumento(
            f"el proveedor rechaza las peticiones ({averia}); el eval no llegó a medir"
        )
    for wait in _BACKOFF_SCHEDULE_S:
        time.sleep(wait)
        out = agent.run(message, session_id=session_id)
        if not _averia_del_proveedor(out):
            return out
        if not _es_saturacion(out):
            raise AveriaDelInstrumento(
                f"el proveedor rechaza las peticiones ({_averia_del_proveedor(out)}); "
                "el eval no llegó a medir"
            )
    raise AveriaDelInstrumento(
        "la ventana de uso de la suscripción sigue saturada (429) tras "
        f"{sum(_BACKOFF_SCHEDULE_S) // 60} minutos de backoff. Reintente cuando la "
        "ventana se recupere. Esto NO dice nada sobre el producto: el eval no llegó "
        "a medir."
    )


def _tokens_of(run_output: Any) -> int:
    metrics = getattr(run_output, "metrics", None)
    if metrics is None:
        return 0
    total = getattr(metrics, "total_tokens", 0) or 0
    if total:
        return int(total)
    inp = getattr(metrics, "input_tokens", 0) or 0
    out = getattr(metrics, "output_tokens", 0) or 0
    return int(inp) + int(out)



@dataclass
class ResultadoEval:
    """Lo que produce una corrida. Se persiste entero: sin esto, cada corrida de
    veinte minutos era información perdida en cuanto terminaba el proceso."""

    session: RCMSession | None
    scenario: dict[str, Any]
    transcript: list[str] = field(default_factory=list)
    herramientas_usadas: set[str] = field(default_factory=set)
    export_path: Path | None = None
    tokens: int = 0
    turnos: int = 0
    motivo_de_corte: str = ""
    #: Qué modelo produjo esta corrida. Va en el volcado porque un acta que no dice
    #: qué midió no se puede interpretar: una tanda entera se midió contra Haiku
    #: creyendo que era Sonnet.
    modelo: str = ""
    #: Fase en la que está el facilitador ahora mismo. El simulador la necesita: su
    #: guion le dice que lance cada sonda «en la fase que indica su campo phase», y
    #: la fase es estado del facilitador — invisible para él si nadie se la pasa.
    fase_actual: int = 1
    #: Un intento por cada llamada a export_excel: (turno, fase, nº de faltantes).
    #: Hace falta el CUÁNDO: la sonda `premature_export` provoca una llamada en la
    #: fase 1, así que "llamó a export_excel" a secas se pone verde sin que el
    #: análisis haya llegado a ninguna parte.
    intentos_de_export: list[tuple[int, int, int]] | None = field(default_factory=list)
    definitivo_antes_de_p6: bool | None = None
    turnos_hasta_p5: int | None = None

    def acta(self) -> Acta:
        return levantar_acta(
            self.session,
            self.scenario,
            transcript=self.transcript,
            herramientas_usadas=self.herramientas_usadas,
            intentos_de_export=self.intentos_de_export,
            definitivo_antes_de_p6=self.definitivo_antes_de_p6,
            turnos_hasta_p5=self.turnos_hasta_p5,
        )

    def como_json(self) -> dict[str, Any]:
        return {
            "modelo": self.modelo,
            "motivo_de_corte": self.motivo_de_corte,
            "turnos": self.turnos,
            "tokens": self.tokens,
            "herramientas_usadas": sorted(self.herramientas_usadas),
            "intentos_de_export": [list(i) for i in self.intentos_de_export],
            "definitivo_antes_de_p6": self.definitivo_antes_de_p6,
            "turnos_hasta_p5": self.turnos_hasta_p5,
            "transcript": self.transcript,
            "session": self.session.model_dump(mode="json") if self.session else None,
        }

    @classmethod
    def desde_json(cls, datos: dict[str, Any], scenario: dict[str, Any]) -> ResultadoEval:
        """Reconstruye una corrida ya pagada. Es lo que permite desarrollar los
        criterios y sus mensajes sin gastar un euro de API."""
        crudo = datos.get("session")
        return cls(
            session=RCMSession.model_validate(crudo) if crudo else None,
            scenario=scenario,
            transcript=list(datos.get("transcript") or []),
            herramientas_usadas=set(datos.get("herramientas_usadas") or []),
            # Sin `or []`: un volcado que NO trae la clave (anterior al registro por
            # turno) no es lo mismo que uno con cero intentos. El primero es «no se
            # puede saber»; el segundo, «nunca lo intentó». Colapsarlos hacía que un
            # volcado viejo acusara al producto de un fallo que no cometió.
            intentos_de_export=(
                [tuple(i) for i in datos["intentos_de_export"]]
                if datos.get("intentos_de_export") is not None
                else None
            ),
            tokens=int(datos.get("tokens") or 0),
            turnos=int(datos.get("turnos") or 0),
            modelo=str(datos.get("modelo") or ""),
            motivo_de_corte=str(datos.get("motivo_de_corte") or ""),
            definitivo_antes_de_p6=datos.get("definitivo_antes_de_p6"),
            turnos_hasta_p5=datos.get("turnos_hasta_p5"),
        )


def run_llm_eval(max_turns: int = 80, token_budget: int = 3_000_000) -> ResultadoEval:
    """Una conversación guiada LLM-contra-LLM. Mide; no juzga.

    No reintenta ante un fallo del producto. Antes lo hacía en silencio y reportaba
    verde si la segunda corrida pasaba: eso no es tolerancia a la varianza, es un
    verde fabricado —si la primera falla y la segunda pasa, lo honesto es 1/2—. El
    único reintento que queda vive en `_run_with_backoff` y es por 429, que es
    avería del instrumento y no del producto.
    """
    # token_budget cuenta tokens TOTALES (entrada+salida) de ambos agentes; la
    # entrada re-envía el historial completo en cada turno, así que crece
    # cuadráticamente — es un tope anti-descontrol, no un objetivo de costo.
    return _run_llm_eval_once(max_turns=max_turns, token_budget=token_budget)


def _construye_settings_del_eval(workdir: Path, exports_dir: Path) -> Any:
    """El eval fija el modelo con versión concreta; producción se queda con el alias.

    Un alias flotante es lo que quieres en producción y lo que NO quieres midiendo:
    un cambio de alias del proveedor te presenta una regresión falsa un martes por
    la mañana. `add_datetime` se apaga porque mete entropía en el prompt de sistema
    de cada corrida y, de paso, invalida el caché de prompt —que en 80 turnos con
    historial creciente es dinero real.

    Nota para quien venga a buscarlo: **no hay `seed`**. La clase `Claude` de agno
    no expone el campo y la API de Anthropic no lo ofrece; pasarlo por
    `request_params` sería un parámetro que el proveedor ignora, o sea determinismo
    de mentira. No lo reintentes.
    """
    from rcm_runbook.config import Settings

    # El modelo se fija EXPLÍCITAMENTE, no se hereda.
    #
    # `Settings` lee el .env de la raíz del proyecto, y ahí puede haber un
    # RCM_MODEL_ID puesto para abaratar el desarrollo local. Heredarlo hace que el
    # eval mida un modelo distinto del que se despliega —pasó: el .env fijaba
    # claude-haiku-4-5 mientras producción servía el default claude-sonnet-4-5, y
    # una tanda entera de corridas midió el modelo equivocado sin que nada lo
    # dijera—. El eval mide el producto, así que por defecto usa lo mismo que
    # produccion: el default del código.
    modelo = os.environ.get("RCM_EVAL_MODEL_ID") or Settings.model_fields["model_id"].default
    cfg = Settings(
        db_path=str(workdir / "eval.db"),
        exports_dir=str(exports_dir),
        model_id=modelo,
        temperature=0.0,
        add_datetime=False,
    )
    cfg = _factura_contra_creditos_si_puede(cfg)
    # Impreso siempre: ni el modelo ni la vía de facturación pueden quedar implícitos.
    via = "suscripción" if cfg.claude_code_oauth_token else "créditos de API"
    print(f"[eval] modelo bajo prueba: {cfg.model_id} · temperature={cfg.temperature} · vía {via}")
    return cfg


def _factura_contra_creditos_si_puede(cfg: Any) -> Any:
    """Prefiere la clave de API a la suscripción, si hay clave.

    Una conversación de 80 turnos satura la ventana de la suscripción, que además
    se comparte con el trabajo interactivo: la primera corrida contra Sonnet se
    pasó 25 minutos de backoff sin conseguir una sola respuesta, mientras la misma
    petición por créditos respondía al instante. Medir el producto no debería
    depender de una ventana que el propio trabajo del día agota.

    Con `RCM_EVAL_USAR_SUSCRIPCION=1` se fuerza el camino de la suscripción.
    """
    import os as _os

    if _os.environ.get("RCM_EVAL_USAR_SUSCRIPCION") == "1":
        return cfg
    if not cfg.claude_code_oauth_token:
        return cfg
    # Sólo se renuncia al OAuth si la clave está donde el SDK va a buscarla: en el
    # entorno del proceso. `Settings` lee el .env por su cuenta, así que mirar allí
    # dejaría el eval sin ninguna credencial cuando nadie ha cargado el fichero.
    if not _os.environ.get("ANTHROPIC_API_KEY"):
        _cargar_env_del_proyecto()
    if not _os.environ.get("ANTHROPIC_API_KEY"):
        return cfg
    return cfg.model_copy(update={"claude_code_oauth_token": ""})


def _cargar_env_del_proyecto() -> None:
    """Vuelca el .env de la raíz al entorno, sin pisar lo que ya esté puesto.

    `Settings` lee ese fichero para sus propios campos, pero el SDK de Anthropic
    lee `ANTHROPIC_API_KEY` del entorno del proceso y no sabe nada del .env.
    """
    raiz = Path(__file__).parents[2] / ".env"
    if not raiz.is_file():
        return
    for linea in raiz.read_text(encoding="utf-8").splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#") or "=" not in linea:
            continue
        clave, _, valor = linea.partition("=")
        os.environ.setdefault(clave.strip(), valor.strip().strip("\"'"))


def ajustes_de_agente_suelto(tmp_path: Path) -> Any:
    """Settings para los evals que hablan con UN agente, sin conversación guiada.

    Comparten dos disciplinas con el arnés largo, y por el mismo motivo: facturan
    contra créditos —una tanda de evals no debe agotar la ventana de la suscripción,
    que se comparte con el trabajo interactivo— y fijan el modelo en el default del
    código, para medir lo que se despliega y no lo que tenga el .env local.
    """
    from rcm_runbook.config import Settings

    cfg = Settings(
        db_path=str(tmp_path / "eval.db"),
        exports_dir=str(tmp_path / "exports"),
        model_id=os.environ.get("RCM_EVAL_MODEL_ID")
        or Settings.model_fields["model_id"].default,
    )
    return _factura_contra_creditos_si_puede(cfg)


def sin_429(agente: Any, mensaje: str) -> Any:
    """Un turno, distinguiendo «no se pudo medir» de «el producto falló».

    Sin esto, un 429 hacía fallar el test igual que un defecto real. Estos dos
    evals son los que cazaron la regresión de la 0.3.2, así que confundir las dos
    cosas aquí es especialmente caro: haría desconfiar del detector.
    """
    salida = agente.run(mensaje)
    if _averia_del_proveedor(salida):
        raise AveriaDelInstrumento(
            "el proveedor devolvió 429 en un turno suelto; el eval no llegó a medir"
        )
    return salida


def _definitivos(exports_dir: Path) -> list[Path]:
    """Entregables DEFINITIVOS en disco, excluyendo borradores explícitamente.

    `rglob("AMEF_*")` ya no casa con `BORRADOR_AMEF_*` porque fnmatch compara el
    nombre completo, pero confiar en esa sutileza es cómo se reabre un agujero en
    silencio el día que alguien cambie el prefijo. Se excluye a mano.
    """
    return [
        p
        for p in exports_dir.rglob(f"{PREFIJO_DEFINITIVO}_*.xlsx")
        if not p.name.startswith(PREFIJO_BORRADOR)
    ]


def _guion_pendiente(
    scenario: dict[str, Any], transcript: list[str], fase_actual: int = 1
) -> str:
    """Lo que a Carlos le queda por decir, recalculado en cada turno.

    El facilitador compensa su ventana de 10 turnos con un digest del estado. El
    simulador no tenía nada: con `num_history_runs=8`, a los treinta turnos ya no
    recuerda qué modos mencionó ni qué sondas lanzó. La instrucción «menciona
    TODOS los modos, incluido el no creíble» vive en el prompt de sistema (que
    persiste), pero saber **si ya lo hizo** vivía en la historia (que se cae). Por
    eso una corrida entera falló por un descarte que nadie llegó a enunciar.

    Esto es determinismo por construcción, no por muestreo: no le fija el fraseo
    —que es lo que el facilitador debe tolerar— sólo le recuerda su propia lista.
    """
    dichos = [t for t in transcript if t.startswith("[CARLOS")]
    from tests.evals.acta import _dice, _tokens

    # Carlos habla suelto ("el problema son los rodamientos"), no parafrasea la
    # ficha del YAML, así que el parecido global del acta no sirve aquí. Se usan
    # los tokens DISCRIMINANTES: los que separan un modo de los otros tres.
    fichas = {
        fm["ref"]: _tokens(f"{fm['description']} {fm['mechanism']}")
        for fm in scenario["failure_modes"]
    }
    discriminantes = {
        ref: t - set().union(*(o for r, o in fichas.items() if r != ref))
        for ref, t in fichas.items()
    }

    def ya_lo_dijo(ref: str) -> bool:
        marcas = discriminantes[ref]
        if not marcas:
            return False
        # Dos marcas, no una: "eje" suelto puede aparecer hablando de rodamientos,
        # y un falso "ya lo dijo" hace que se salte el modo — que es justo el fallo
        # que esto viene a arreglar. Ante la duda, que lo repita.
        hacen_falta = min(2, len(marcas))
        return any(len(marcas & _tokens(t)) >= hacen_falta for t in dichos)

    pendientes = [
        f"{fm['ref']} ({fm['description']})"
        for fm in scenario["failure_modes"]
        if not ya_lo_dijo(fm["ref"])
    ]
    sin_lanzar = [
        p for p in scenario.get("adversarial_probes", [])
        if not _dice(dichos, p["utterance"])
    ]
    # La fase toca lanzarla cuando la conversación LA ALCANZA o la pasa: el guion
    # dice «en la fase que indica su campo phase», y esa fase es estado del
    # facilitador. Sin pasársela, la condición era inobservable para el simulador y
    # las sondas no se lanzaban nunca — cero de cinco en veinte turnos.
    toca_ahora = [p for p in sin_lanzar if p["phase"] <= fase_actual]
    lineas = [
        "Recordatorio de TU guion (no lo cites; úsalo para no repetirte).",
        f"- El análisis va por la FASE {fase_actual}.",
        "- Modos de falla que aún NO has mencionado: "
        + (", ".join(pendientes) if pendientes else "ninguno, ya los diste todos"),
    ]
    if toca_ahora:
        lineas.append(
            "- SONDAS QUE TE TOCA LANZAR YA (una por turno, con su texto literal): "
            + " | ".join(f'{p["id"]}: "{p["utterance"]}"' for p in toca_ahora)
        )
    else:
        pendientes_futuras = [f'{p["id"]} (fase {p["phase"]})' for p in sin_lanzar]
        resumen = (
            ", ".join(pendientes_futuras) if pendientes_futuras
            else "ninguna, ya las lanzaste todas"
        )
        lineas.append("- Sondas pendientes, aún no toca: " + resumen)
    return "\n".join(lineas)


def _estado_rcm(facilitator: Any, session_id: str) -> RCMSession | None:
    try:
        state = facilitator.get_session_state(session_id=session_id)
    except Exception:
        return None
    raw = (state or {}).get(t.SESSION_KEY)
    if raw is None:
        return None
    try:
        return RCMSession.model_validate(raw)
    except Exception:
        return None


def _run_llm_eval_once(max_turns: int, token_budget: int) -> ResultadoEval:
    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb

    from rcm_runbook.agent.factory import build_agent, build_model

    scenario = load_scenario()
    scenario_yaml = SCENARIO_PATH.read_text(encoding="utf-8")

    workdir = Path(tempfile.mkdtemp(prefix="rcm-llm-eval-"))
    exports_dir = workdir / "exports"
    exports_dir.mkdir()
    cfg = _construye_settings_del_eval(workdir, exports_dir)

    resultado = ResultadoEval(session=None, scenario=scenario, modelo=cfg.model_id)
    facilitator = build_agent(cfg)
    # El simulador se queda con el muestreo del proveedor a propósito. Con
    # temperature=0 entra en bucles —repite la misma frase hasta el corte— y, peor,
    # fija el orden en que Carlos suelta los modos de falla: el eval empezaría a
    # pasar por memorizar un guion en vez de por tolerar variedad de fraseo, que es
    # justo lo que el facilitador tiene que saber hacer.
    cfg_simulador = cfg.model_copy(update={"temperature": None})
    simulator = Agent(
        name="Carlos (simulador de interesado)",
        model=build_model(cfg_simulador),
        db=SqliteDb(db_file=str(workdir / "sim.db")),  # sin db no hay historial
        instructions=SIMULATOR_PROMPT_ES.format(scenario_yaml=scenario_yaml),
        add_history_to_context=True,
        num_history_runs=8,
        dependencies={"guion_pendiente": lambda: _guion_pendiente(
            scenario, resultado.transcript, resultado.fase_actual
        )},
        add_dependencies_to_context=True,
        markdown=False,
        telemetry=False,
    )

    # export_excel escribe en el settings global de la app — redirígelo al tmp del eval
    previous_exports_dir = t.settings.exports_dir
    t.settings.exports_dir = str(exports_dir)

    session_id = f"eval-llm-{uuid.uuid4().hex[:8]}"
    sim_session_id = f"{session_id}-sim"
    message = (
        "Hola, soy Carlos Mendoza, ingeniero de mantenimiento. Con María Torres de "
        "operaciones queremos hacer el análisis RCM de la bomba P-101. ¿Empezamos?"
    )
    try:
        for turno in range(max_turns):
            resultado.turnos = turno + 1
            fac_out = _run_with_backoff(facilitator, message, session_id)
            resultado.tokens += _tokens_of(fac_out)
            for llamada in getattr(fac_out, "tools", None) or []:
                nombre = getattr(llamada, "tool_name", None)
                if nombre:
                    resultado.herramientas_usadas.add(nombre)
            reply = str(fac_out.content or "")
            # Sin truncar: el transcript es la evidencia, y a 400 caracteres se
            # perdía justo el turno que explicaba el fallo.
            resultado.transcript.append(f"[FACILITADOR t{turno}] {reply}")

            # El progreso se lee del ESTADO, no de la prosa: el agente parafrasea.
            estado = _estado_rcm(facilitator, session_id)
            if estado is not None:
                resultado.fase_actual = estado.phase.value
                llamadas = {
                    getattr(c, "tool_name", None)
                    for c in (getattr(fac_out, "tools", None) or [])
                }
                if "export_excel" in llamadas:
                    resultado.intentos_de_export.append(
                        (turno, estado.phase.value, len(compliance.export_blockers(estado)))
                    )
                if resultado.turnos_hasta_p5 is None and estado.phase.value >= 5:
                    resultado.turnos_hasta_p5 = turno
                if _definitivos(exports_dir) and resultado.definitivo_antes_de_p6 is None:
                    # El definitivo sólo debe existir con el análisis cerrado.
                    resultado.definitivo_antes_de_p6 = bool(
                        compliance.export_blockers(estado)
                    )

            if _definitivos(exports_dir):
                resultado.motivo_de_corte = "entregable definitivo en disco"
                break
            if resultado.tokens > token_budget:
                raise AveriaDelInstrumento(
                    f"presupuesto de tokens agotado ({resultado.tokens} > "
                    f"{token_budget}) antes de completar la sesión"
                )

            sim_out = _run_with_backoff(simulator, reply, sim_session_id)
            resultado.tokens += _tokens_of(sim_out)
            message = str(sim_out.content or "")
            resultado.transcript.append(f"[CARLOS t{turno}] {message}")
            if _SIM_DONE_MARKER in message:
                resultado.motivo_de_corte = "el simulador dio la sesión por terminada"
                break
        else:
            resultado.motivo_de_corte = f"no terminó en {max_turns} turnos"

        resultado.session = _estado_rcm(facilitator, session_id)
        if resultado.session is None and not resultado.motivo_de_corte:
            resultado.motivo_de_corte = "no se encontró el estado RCM en la sesión"

        # El entregable debe reproducirse limpio desde el estado final.
        if resultado.session is not None:
            try:
                camino = export_xlsx(resultado.session, str(exports_dir))
                resultado.export_path = camino if camino.is_file() else None
            except Exception as exc:  # el porqué importa más que el hecho
                resultado.transcript.append(f"[ARNÉS] export desde estado final falló: {exc}")
        return resultado
    finally:
        t.settings.exports_dir = previous_exports_dir
