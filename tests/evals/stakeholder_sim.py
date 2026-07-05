"""Eval harness: stakeholder simulator vs. RCM facilitator.

Two entry points:
- run_scripted_eval()  — NO LLM: drives the facilitator's tools directly from the
  YAML ground-truth scenario (same pattern as tests/unit/test_tools.py) and returns
  the final RCMSession. Validates the scenario is complete and all gates go green.
- run_llm_eval()       — LLM-vs-LLM: the real facilitator agent (build_agent) talks
  to a second Agno agent that role-plays maintenance engineer "Carlos", answering
  STRICTLY from the YAML ground truth and firing scripted adversarial probes.
  Asserts on FINAL SESSION STATE (gates, policies, HITL, export) — never on prose.

Both raise AssertionError with a Spanish summary of what failed.
"""

from __future__ import annotations

import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from rcm_runbook.agent import tools as t
from rcm_runbook.engine import compliance
from rcm_runbook.export.excel import export_xlsx
from rcm_runbook.models.session import RCMSession

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
            out = _call(t.calculate_ffi, ctx, method=ffi["method"],
                        mtive_hours=ffi["mtive_hours"], mted_hours=ffi["mted_hours"],
                        mmf_hours=ffi["mmf_hours"])
            _expect("FFI" in out and out.startswith("✔"), "el cálculo de FFI falló", out)
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
                  requires_shutdown=task.get("requires_shutdown", False))
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
    """Assert on FINAL STATE, never on prose."""
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

    expected_policies = sorted(d["expected_policy"] for d in scenario["decisions"])
    actual_policies = sorted(
        d.policy.value for fmid, d in session.decisions.items()
        if session.failure_modes[fmid].credible
    )
    if actual_policies != expected_policies:
        failures.append(
            f"Las políticas no coinciden con el escenario: esperadas {expected_policies}, "
            f"obtenidas {actual_policies}."
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
- Responde UNA pregunta a la vez, breve y natural, como en una reunión de planta.
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

_EXPORT_DONE_MARKERS = ("Entregable definitivo exportado", "/exports/")
_SIM_DONE_MARKER = "FIN DE SESION"


def _tail(transcript: list[str], n: int = 8) -> str:
    """Últimos turnos de la conversación — diagnóstico cuando el eval falla."""
    return "Últimos turnos:\n" + "\n".join(transcript[-n:]) if transcript else ""


_RATE_LIMIT_MARKERS = ("rate_limit_error", "Error code: 429")
# Backoff ante 429 (ventana de suscripción saturada): espera hasta ~25 min en total.
_BACKOFF_SCHEDULE_S = (60, 120, 240, 480, 600)


def _is_rate_limited(output: Any) -> bool:
    content = str(getattr(output, "content", "") or "")
    return any(m in content for m in _RATE_LIMIT_MARKERS)


def _run_with_backoff(agent: Any, message: str, session_id: str) -> Any:
    """Ejecuta un turno; ante 429 espera y REINTENTA el mismo turno (no lo consume).

    agno captura el error del proveedor y lo devuelve como contenido del RunOutput,
    así que se detecta por contenido, no por excepción. Si la ventana de la
    suscripción no se recupera tras el backoff completo, aborta con un mensaje claro
    en vez de quemar turnos conversando con errores.
    """
    out = agent.run(message, session_id=session_id)
    if not _is_rate_limited(out):
        return out
    for wait in _BACKOFF_SCHEDULE_S:
        time.sleep(wait)
        out = agent.run(message, session_id=session_id)
        if not _is_rate_limited(out):
            return out
    raise AssertionError(
        "EVAL ABORTADO — la ventana de uso de la suscripción sigue saturada (429) "
        f"tras {sum(_BACKOFF_SCHEDULE_S) // 60} minutos de backoff. "
        "Reintente cuando la ventana se recupere."
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


def run_llm_eval(max_turns: int = 80, token_budget: int = 3_000_000) -> RCMSession:
    # token_budget cuenta tokens TOTALES (entrada+salida) de ambos agentes; la
    # entrada re-envía el historial completo en cada turno, así que crece
    # cuadráticamente — es un tope anti-descontrol, no un objetivo de costo.
    """LLM-vs-LLM guided session with a single automatic retry."""
    try:
        return _run_llm_eval_once(max_turns=max_turns, token_budget=token_budget)
    except AssertionError:
        # Un único reintento automático: las conversaciones LLM son estocásticas.
        return _run_llm_eval_once(max_turns=max_turns, token_budget=token_budget)


def _run_llm_eval_once(max_turns: int, token_budget: int) -> RCMSession:
    from agno.agent import Agent

    from rcm_runbook.agent.factory import build_agent, build_model
    from rcm_runbook.config import Settings

    scenario = load_scenario()
    scenario_yaml = SCENARIO_PATH.read_text(encoding="utf-8")

    workdir = Path(tempfile.mkdtemp(prefix="rcm-llm-eval-"))
    exports_dir = workdir / "exports"
    exports_dir.mkdir()
    cfg = Settings(db_path=str(workdir / "eval.db"), exports_dir=str(exports_dir))

    from agno.db.sqlite import SqliteDb

    facilitator = build_agent(cfg)
    simulator = Agent(
        name="Carlos (simulador de interesado)",
        model=build_model(cfg),
        db=SqliteDb(db_file=str(workdir / "sim.db")),  # sin db no hay historial
        instructions=SIMULATOR_PROMPT_ES.format(scenario_yaml=scenario_yaml),
        add_history_to_context=True,
        markdown=False,
        telemetry=False,
    )

    # export_excel escribe en el settings global de la app — redirígelo al tmp del eval
    previous_exports_dir = t.settings.exports_dir
    t.settings.exports_dir = str(exports_dir)

    session_id = f"eval-llm-{uuid.uuid4().hex[:8]}"
    sim_session_id = f"{session_id}-sim"
    tokens_used = 0
    export_confirmed = False
    message = (
        "Hola, soy Carlos Mendoza, ingeniero de mantenimiento. Con María Torres de "
        "operaciones queremos hacer el análisis RCM de la bomba P-101. ¿Empezamos?"
    )
    transcript: list[str] = []
    try:
        for _turn in range(max_turns):
            fac_out = _run_with_backoff(facilitator, message, session_id)
            tokens_used += _tokens_of(fac_out)
            reply = str(fac_out.content or "")
            transcript.append(f"[FACILITADOR t{_turn}] {reply[:400]}")
            # Estado, no prosa: el export definitivo se detecta por el .xlsx en disco
            # (el agente puede parafrasear el resultado de la herramienta).
            if list(exports_dir.rglob("*.xlsx")):
                export_confirmed = True
                break
            if any(marker in reply for marker in _EXPORT_DONE_MARKERS):
                export_confirmed = True
                break
            if tokens_used > token_budget:
                raise AssertionError(
                    f"EVAL FALLIDO — presupuesto de tokens agotado "
                    f"({tokens_used} > {token_budget}) antes de completar la sesión.\n"
                    + _tail(transcript)
                )
            sim_out = _run_with_backoff(simulator, reply, sim_session_id)
            tokens_used += _tokens_of(sim_out)
            message = str(sim_out.content or "")
            transcript.append(f"[CARLOS t{_turn}] {message[:400]}")
            if _SIM_DONE_MARKER in message:
                export_confirmed = bool(list(exports_dir.rglob("*.xlsx")))
                break
        else:
            raise AssertionError(
                f"EVAL FALLIDO — la sesión no terminó en {max_turns} turnos "
                f"(tokens usados: {tokens_used}).\n" + _tail(transcript)
            )

        if not export_confirmed:
            raise AssertionError(
                "EVAL FALLIDO — no se generó el export definitivo (.xlsx) en disco.\n"
                + _tail(transcript)
            )

        # Estado final desde la base de sesiones del agente (no desde la prosa)
        state = facilitator.get_session_state(session_id=session_id)
        raw = (state or {}).get(t.SESSION_KEY)
        if raw is None:
            raise AssertionError(
                "EVAL FALLIDO — no se encontró el estado RCM en la sesión del facilitador."
            )
        session = RCMSession.model_validate(raw)
        _assert_final_state(session, scenario)

        # El export debe reproducirse limpio desde el estado final
        export_path = export_xlsx(session, str(exports_dir))
        if not export_path.is_file():
            raise AssertionError("EVAL FALLIDO — el archivo exportado no existe.")
        return session
    finally:
        t.settings.exports_dir = previous_exports_dir
