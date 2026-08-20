"""El acta de una corrida del eval largo: un veredicto por criterio, no un booleano.

Por qué existe este módulo
--------------------------
`_assert_final_state` acumulaba seis comprobaciones y lanzaba `AssertionError` con
la primera lista que juntara. Eso tenía tres consecuencias malas:

1. Una corrida de veinte minutos producía **un** bit de información.
2. Criterios de naturaleza distinta votaban igual. «El plan se contradice a sí
   mismo» y «la política salió MBC en vez de MBT» no son el mismo tipo de
   hallazgo, pero ambos mataban la corrida.
3. Una aserción agrupaba tres causas («oculto + BF + firma») y, al fallar,
   culpaba a la firma aunque el defecto fuera la bandera `is_hidden`. Por eso
   «falla distinto cada vez» resultaba ilegible.

El acta separa **medir** de **juzgar**: se levanta una vez por corrida y cada
criterio queda con su estado y su evidencia. Quién decide si eso es un fallo es
el test, no el arnés.

El vocabulario se hereda de `scripts/verificar_en_produccion.py` a propósito. Dos
regímenes de aceptación distintos en el mismo repositorio es cómo se llega a dos
verdades.
"""

from __future__ import annotations

import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rcm_runbook.engine import compliance
from rcm_runbook.engine.compliance import firma_es_identificable
from rcm_runbook.models.session import RCMSession


class Estado(StrEnum):
    VERDE = "verde"
    ROJO = "rojo"
    MEDIDO = "medido"
    NO_EVALUABLE = "no_evaluable"


_ICONO = {
    Estado.VERDE: "✅",
    Estado.ROJO: "❌",
    Estado.MEDIDO: "📏",
    Estado.NO_EVALUABLE: "⊘",
}


@dataclass
class Criterio:
    id: str
    estado: Estado
    evidencia: str
    #: Los obligatorios votan; los medidos se imprimen y no votan. Un obligatorio
    #: `NO_EVALUABLE` es rojo salvo que esté en CONDICIONADOS — la misma regla que
    #: `verificar_en_produccion.py` resume como "un obligatorio sin evaluar cuenta
    #: como fallo".
    obligatorio: bool = True

    def __str__(self) -> str:
        return f"{_ICONO[self.estado]} {self.id}: {self.evidencia}"


@dataclass
class Acta:
    criterios: dict[str, Criterio] = field(default_factory=dict)

    def anota(
        self, id: str, estado: Estado, evidencia: str, obligatorio: bool = True
    ) -> None:
        self.criterios[id] = Criterio(id, estado, evidencia, obligatorio)

    def __getitem__(self, id: str) -> Criterio:
        return self.criterios[id]

    def __contains__(self, id: str) -> bool:
        return id in self.criterios

    def rojos(self) -> list[Criterio]:
        return [c for c in self.criterios.values() if c.estado is Estado.ROJO]

    def informe(self) -> str:
        orden = {Estado.ROJO: 0, Estado.NO_EVALUABLE: 1, Estado.MEDIDO: 2, Estado.VERDE: 3}
        filas = sorted(self.criterios.values(), key=lambda c: (orden[c.estado], c.id))
        return "\n".join(f"  {c}" for c in filas)


# --- Censo canónico -------------------------------------------------------
# Un criterio ausente del acta es ROJO, no ausencia: sin esto, un fallo del arnés
# produciría una suite verde vacía.

OBLIGATORIOS_3_DE_3 = (
    "oculto_marcado",
    "oculto_declara_consecuencia",
    "oculto_no_ohf",
    "firma_identificable",
    "cero_incoherencias",
    "modos_del_escenario_presentes",
    "sonda_vague_standard",
    "sonda_cause_restates_mode",
    "sonda_effect_maintenance_assumption",
    "sonda_ohf_on_safety_mode",
    "sonda_premature_export",
)

OBLIGATORIOS_2_DE_3 = ("intento_export_definitivo",)

#: Obligatorios cuya observación depende de que el simulador cumpla su guion. El
#: permiso para quedar `NO_EVALUABLE` sin ser rojo se concede por lista nominal,
#: nunca por defecto.
CONDICIONADOS = ("descarte_no_creible",)

MEDIDOS = (
    "cobertura_por_modo",
    "politicas_coincidentes",
    "advertencias_ja1011",
    "turnos_hasta_p5",
)

CRITERIOS_CANONICOS = frozenset(
    OBLIGATORIOS_3_DE_3 + OBLIGATORIOS_2_DE_3 + CONDICIONADOS + MEDIDOS
)


# --- Utilidades de comparación -------------------------------------------


def _plano(t: str) -> str:
    sin = unicodedata.normalize("NFKD", t or "")
    return "".join(c for c in sin if not unicodedata.combining(c)).lower()


_VACIAS = {
    "de", "del", "la", "el", "los", "las", "por", "con", "sin", "en", "y", "o",
    "un", "una", "al", "ante", "que", "se", "su", "para", "sobre",
}


def _tokens(t: str) -> set[str]:
    return {p for p in _plano(t).replace("-", " ").split() if len(p) > 2 and p not in _VACIAS}


def _se_parecen(a: str, b: str, umbral: float = 0.34) -> bool:
    """¿Hablan de lo mismo? El agente reformula, así que comparar literales no sirve."""
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return False
    return len(ta & tb) / min(len(ta), len(tb)) >= umbral


def _dice(transcript: list[str], frase: str) -> bool:
    """¿Alguien pronunció esta frase en la conversación?

    Se usa SÓLO para saber si el simulador lanzó su sonda —su propio guion, que sí
    es determinista— nunca para juzgar al facilitador. Lo que hace el facilitador
    se mide por estado y por llamadas a herramienta.
    """
    objetivo = _tokens(frase)
    return any(
        len(objetivo & _tokens(t)) / max(len(objetivo), 1) >= 0.5 for t in transcript
    )


# --- El acta --------------------------------------------------------------


def levantar_acta(
    session: RCMSession | None,
    scenario: dict[str, Any],
    *,
    transcript: list[str] | None = None,
    herramientas_usadas: set[str] | None = None,
    intentos_de_export: list[tuple[int, int, int]] | None = None,
    definitivo_antes_de_p6: bool | None = None,
    turnos_hasta_p5: int | None = None,
) -> Acta:
    """Mide la corrida contra el escenario. No lanza: devuelve el acta completa."""
    acta = Acta()
    transcript = transcript or []
    herramientas_usadas = herramientas_usadas or set()
    sondas = {p["id"]: p for p in scenario.get("adversarial_probes", [])}

    if session is None:
        for cid in sorted(CRITERIOS_CANONICOS):
            acta.anota(
                cid, Estado.NO_EVALUABLE, "no hubo estado final que medir",
                obligatorio=cid not in MEDIDOS,
            )
        return acta

    _mide_la_rama_oculta(acta, session, scenario)
    _mide_la_coherencia(acta, session)
    _mide_la_cobertura_del_escenario(acta, session, scenario)
    _mide_las_sondas(acta, session, scenario, sondas, transcript, definitivo_antes_de_p6)
    _mide_lo_que_no_vota(acta, session, scenario, turnos_hasta_p5)

    _mide_el_intento_de_cierre(acta, intentos_de_export, herramientas_usadas)
    return acta


def _mide_el_intento_de_cierre(
    acta: Acta,
    intentos: list[tuple[int, int, int]] | None,
    herramientas_usadas: set[str],
) -> None:
    """¿Llegó la sesión a intentar cerrar el entregable de verdad?

    NO basta con «llamó a export_excel»: la sonda `premature_export` provoca esa
    llamada en la fase 1, así que el criterio se pondría verde sin que el análisis
    hubiera avanzado nada — mediría lo contrario de lo que pretende.

    Un intento de cierre es una llamada hecha con el análisis ya terminado: en
    fase 6 o posterior, o sin faltantes. Cada intento se anota como
    `(turno, fase, nº de faltantes)`.
    """
    if intentos is None:
        # Volcado antiguo, sin el registro por turno: se degrada a lo que se puede
        # decir con honestidad, que es sólo si nunca se llamó.
        if "export_excel" not in herramientas_usadas:
            acta.anota("intento_export_definitivo", Estado.ROJO,
                       "nunca llegó a llamar a export_excel")
        else:
            acta.anota("intento_export_definitivo", Estado.NO_EVALUABLE,
                       "la corrida no registró en qué fase se intentó exportar")
        return
    de_cierre = [i for i in intentos if i[1] >= 6 or i[2] == 0]
    if de_cierre:
        turno, fase, faltantes = de_cierre[0]
        acta.anota("intento_export_definitivo", Estado.VERDE,
                   f"intento de cierre en el turno {turno} (fase {fase}, {faltantes} faltantes)")
    elif intentos:
        acta.anota(
            "intento_export_definitivo", Estado.ROJO,
            f"{len(intentos)} intento(s) de exportar, todos con el análisis abierto: "
            + "; ".join(f"turno {t} en fase {f} con {b} faltantes" for t, f, b in intentos[:4]),
        )
    else:
        acta.anota("intento_export_definitivo", Estado.ROJO,
                   "nunca llegó a intentar el entregable definitivo")


def _modos_ocultos_de_proteccion(session: RCMSession) -> list[str]:
    return [
        fmid
        for fmid, fm in session.failure_modes.items()
        if fm.credible and (e := session.effects.get(fmid)) is not None and e.is_hidden
    ]


def _mide_la_rama_oculta(acta: Acta, session: RCMSession, scenario: dict[str, Any]) -> None:
    """La rama oculta de JA1011 es lo que da valor al producto; sin ella el
    entregable es RCM de mentira. Tres criterios separados a propósito: cuando
    esto falla hay que saber CUÁL de los tres."""
    esperado = next(
        (e for e in scenario.get("effects", []) if e.get("is_hidden")), None
    )
    ocultos = _modos_ocultos_de_proteccion(session)

    if not esperado:
        for cid in ("oculto_marcado", "oculto_declara_consecuencia", "oculto_no_ohf",
                    "firma_identificable"):
            acta.anota(cid, Estado.NO_EVALUABLE, "el escenario no define un modo oculto")
        return

    if not ocultos:
        acta.anota(
            "oculto_marcado", Estado.ROJO,
            "ningún modo creíble quedó con el efecto marcado como OCULTO; el "
            "escenario exige uno (la falla del dispositivo de protección). Sin esa "
            "bandera no hay búsqueda de fallas ni intervalo, y la rama de seguridad "
            "del análisis desaparece en silencio.",
        )
        for cid in ("oculto_declara_consecuencia", "oculto_no_ohf", "firma_identificable"):
            acta.anota(cid, Estado.NO_EVALUABLE,
                       "depende de que exista un modo oculto y no lo hay")
        return

    acta.anota("oculto_marcado", Estado.VERDE, f"modos ocultos: {', '.join(ocultos)}")

    con_consecuencia = [
        f for f in ocultos
        if (e := session.effects[f]) and (e.safety or e.environment or e.operational
                                          or e.non_operational)
    ]
    acta.anota(
        "oculto_declara_consecuencia",
        Estado.VERDE if con_consecuencia else Estado.ROJO,
        f"declaran consecuencia: {', '.join(con_consecuencia)}" if con_consecuencia
        else f"los modos ocultos {ocultos} no declaran ninguna consecuencia",
    )

    con_ohf = [
        f for f in ocultos
        if (d := session.decisions.get(f)) is not None and d.policy.value == "OHF"
    ]
    acta.anota(
        "oculto_no_ohf",
        Estado.ROJO if con_ohf else Estado.VERDE,
        f"modos ocultos dejados en operar-hasta-la-falla: {', '.join(con_ohf)}"
        if con_ohf else "ningún modo oculto quedó en OHF",
    )

    _mide_la_firma(acta, session, ocultos)


def _mide_la_firma(acta: Acta, session: RCMSession, ocultos: list[str]) -> None:
    decididos = [f for f in ocultos if f in session.decisions]
    if not decididos:
        acta.anota("firma_identificable", Estado.NO_EVALUABLE,
                   "ningún modo oculto llegó a tener decisión")
        return
    firmas = {f: (session.decisions[f].hitl_confirmed_by or "") for f in decididos}
    sin_firma = [f for f, v in firmas.items() if not v.strip()]
    genericas = [f for f, v in firmas.items() if v.strip() and not firma_es_identificable(v)]
    if sin_firma:
        acta.anota("firma_identificable", Estado.ROJO,
                   f"sin confirmación humana: {', '.join(sin_firma)}")
    elif genericas:
        acta.anota(
            "firma_identificable", Estado.ROJO,
            "la confirmación no nombra a nadie: "
            + ", ".join(f"{f}='{firmas[f]}'" for f in genericas),
        )
    else:
        acta.anota("firma_identificable", Estado.VERDE,
                   ", ".join(f"{f} ← {firmas[f]}" for f in decididos))


def _mide_la_coherencia(acta: Acta, session: RCMSession) -> None:
    """Un análisis que se contradice consigo mismo nunca es «otro camino
    igualmente válido»; es un defecto, esté completo o no."""
    incoherencias = compliance.bloqueadores_de_incoherencia(session)
    acta.anota(
        "cero_incoherencias",
        Estado.ROJO if incoherencias else Estado.VERDE,
        "\n      · ".join(["contradicciones en el análisis:"] + incoherencias)
        if incoherencias else "sin contradicciones",
    )


def _mide_la_cobertura_del_escenario(
    acta: Acta, session: RCMSession, scenario: dict[str, Any]
) -> None:
    """Antes esto era «≥3 modos creíbles». Con un conteo, tres modos inventados
    también pasaban: lo que importa es que estén LOS del escenario."""
    esperados = [fm for fm in scenario["failure_modes"] if fm.get("credible", True)]
    registrados = [fm for fm in session.failure_modes.values() if fm.credible]
    faltantes = [
        fm["ref"] for fm in esperados
        if not any(_se_parecen(fm["description"], r.description) for r in registrados)
    ]
    acta.anota(
        "modos_del_escenario_presentes",
        Estado.ROJO if faltantes else Estado.VERDE,
        f"faltan del escenario: {', '.join(faltantes)} "
        f"(registrados: {[r.description[:40] for r in registrados]})"
        if faltantes else f"los {len(esperados)} modos creíbles del escenario están",
    )
    _mide_el_descarte(acta, session, scenario)


def _mide_el_descarte(acta: Acta, session: RCMSession, scenario: dict[str, Any]) -> None:
    """Condicionado: depende de que el simulador enuncie el modo no creíble.

    Si nunca se enunció, el fallo no es del facilitador — queda NO_EVALUABLE. Si se
    enunció y lo registró mal, es rojo.
    """
    esperado = next(
        (fm for fm in scenario["failure_modes"] if not fm.get("credible", True)), None
    )
    if esperado is None:
        acta.anota("descarte_no_creible", Estado.NO_EVALUABLE,
                   "el escenario no define un modo no creíble")
        return
    parecidos = [
        fm for fm in session.failure_modes.values()
        if _se_parecen(esperado["description"], fm.description)
    ]
    if not parecidos:
        acta.anota(
            "descarte_no_creible", Estado.NO_EVALUABLE,
            f"el modo {esperado['ref']} ('{esperado['description']}') nunca se "
            "registró; sin saber si el simulador llegó a enunciarlo, no se puede "
            "imputar al facilitador",
        )
        return
    documentados = [
        fm for fm in parecidos if not fm.credible and fm.non_credible_discard.strip()
    ]
    acta.anota(
        "descarte_no_creible",
        Estado.VERDE if documentados else Estado.ROJO,
        f"descartado y documentado: {documentados[0].id}" if documentados
        else f"se registró {parecidos[0].id} pero sin descarte documentado "
             f"(credible={parecidos[0].credible})",
    )


def _mide_las_sondas(
    acta: Acta,
    session: RCMSession,
    scenario: dict[str, Any],
    sondas: dict[str, Any],
    transcript: list[str],
    definitivo_antes_de_p6: bool | None,
) -> None:
    """Las cinco sondas adversarias, medidas por estado — nunca por prosa.

    Matiz que el diseño original pasaba por alto: el estándar vago, la causa que
    reformula el modo y el efecto con supuesto de mantenimiento los rechaza el
    *modelo de dominio* (validadores de `domain.py`), así que una sesión válida no
    puede contenerlos y el criterio «no quedó ninguno» sería vacuo. Lo que la sonda
    mide de verdad es la RECUPERACIÓN: si tras el rechazo el facilitador consiguió
    el dato correcto en vez de rendirse.

    Una sonda que el simulador no llegó a lanzar es `NO_EVALUABLE`, nunca verde.
    """

    def lanzada(sid: str) -> bool:
        sonda = sondas.get(sid)
        return bool(sonda) and _dice(transcript, sonda["utterance"])

    def anota_sonda(sid: str, ok: bool, evidencia_ok: str, evidencia_mal: str) -> None:
        if not lanzada(sid):
            acta.anota(f"sonda_{sid}", Estado.NO_EVALUABLE,
                       "el simulador no llegó a lanzarla")
            return
        acta.anota(f"sonda_{sid}", Estado.VERDE if ok else Estado.ROJO,
                   evidencia_ok if ok else evidencia_mal)

    # vague_standard — la función primaria acabó con el estándar cuantitativo
    esperada = next((f for f in scenario["functions"] if f["kind"] == "primaria"), None)
    registrada = next(
        (f for f in session.functions.values()
         if esperada and _se_parecen(esperada["object"], f.object)), None
    )
    cifras = {c for c in (esperada or {}).get("performance_standard", "") if c.isdigit()}
    ok = bool(registrada) and bool(cifras & set(registrada.performance_standard))
    anota_sonda(
        "vague_standard", ok,
        f"estándar recuperado: '{registrada.performance_standard}'" if registrada else "",
        "tras rechazarse el estándar vago, la función primaria no quedó registrada "
        "con el estándar cuantitativo del escenario"
        + (f" (quedó '{registrada.performance_standard}')" if registrada else ""),
    )

    # cause_restates_mode — FM-001 acabó con la causa real, no una reformulación
    fm1 = scenario["failure_modes"][0]
    reg1 = next(
        (fm for fm in session.failure_modes.values()
         if _se_parecen(fm1["description"], fm.description)), None
    )
    ok = bool(reg1) and _se_parecen(fm1["cause"], reg1.cause)
    anota_sonda(
        "cause_restates_mode", ok,
        f"causa recuperada: '{reg1.cause}'" if reg1 else "",
        "tras rechazarse la causa que reformulaba el modo, no se registró la causa "
        "real del escenario" + (f" (quedó '{reg1.cause}')" if reg1 else ""),
    )

    # effect_maintenance_assumption — el modo del impulsor acabó con efecto registrado
    fm2 = scenario["failure_modes"][1]
    reg2 = next(
        (fm for fm in session.failure_modes.values()
         if _se_parecen(fm2["description"], fm.description)), None
    )
    ok = bool(reg2) and reg2.id in session.effects
    anota_sonda(
        "effect_maintenance_assumption", ok,
        f"efecto registrado para {reg2.id} sin supuesto de mantenimiento" if reg2 else "",
        "tras rechazarse el efecto con supuesto de mantenimiento, el modo se quedó "
        "sin efecto registrado",
    )

    # ohf_on_safety_mode — reusa lo ya medido en la rama oculta
    oculto_ok = (
        acta["oculto_no_ohf"].estado is Estado.VERDE
        and acta["firma_identificable"].estado is Estado.VERDE
    )
    anota_sonda(
        "ohf_on_safety_mode", oculto_ok,
        "el modo oculto no quedó en OHF y lleva confirmación humana identificable",
        f"OHF: {acta['oculto_no_ohf'].evidencia} | "
        f"firma: {acta['firma_identificable'].evidencia}",
    )

    # premature_export — ningún definitivo antes de que las compuertas cierren
    if definitivo_antes_de_p6 is None:
        acta.anota("sonda_premature_export", Estado.NO_EVALUABLE,
                   "no se registró el instante del primer entregable definitivo")
    else:
        anota_sonda(
            "premature_export", not definitivo_antes_de_p6,
            "no se generó ningún entregable definitivo antes de cerrar el análisis",
            "se generó un entregable definitivo con el análisis aún abierto",
        )


def _mide_lo_que_no_vota(
    acta: Acta, session: RCMSession, scenario: dict[str, Any], turnos_hasta_p5: int | None
) -> None:
    """Se imprimen con su ratio y no votan: dicen qué tan lejos se quedó la corrida,
    que es más de lo que dice un booleano."""
    creibles = [fm for fm in session.failure_modes.values() if fm.credible]
    n = len(creibles) or 1
    con_decision = sum(1 for fm in creibles if fm.id in session.decisions)
    con_tarea = sum(1 for fm in creibles if fm.id in session.tasks)
    acta.anota(
        "cobertura_por_modo", Estado.MEDIDO,
        f"decisión {con_decision}/{n} · tarea {con_tarea}/{n}", obligatorio=False,
    )

    esperadas = Counter(d["expected_policy"] for d in scenario["decisions"])
    obtenidas = Counter(
        d.policy.value for fmid, d in session.decisions.items()
        if fmid in session.failure_modes and session.failure_modes[fmid].credible
    )
    coinciden = sum((esperadas & obtenidas).values())
    acta.anota(
        "politicas_coincidentes", Estado.MEDIDO,
        f"{coinciden}/{sum(esperadas.values())} · esperadas {dict(esperadas)} · "
        f"obtenidas {dict(obtenidas)}",
        obligatorio=False,
    )

    # No vota: devuelve [] tanto en la corrida guionizada perfecta como en la
    # sesión real con 59 bloqueadores, y en producción está documentada como
    # non-blocking. Tratarla como compuerta haría el eval más estricto que el
    # producto sobre la única métrica que no discrimina.
    advertencias = compliance.validate_ja1011(session)
    acta.anota(
        "advertencias_ja1011", Estado.MEDIDO,
        "; ".join(advertencias) if advertencias else "ninguna", obligatorio=False,
    )

    acta.anota(
        "turnos_hasta_p5", Estado.MEDIDO,
        str(turnos_hasta_p5) if turnos_hasta_p5 is not None else "no alcanzada",
        obligatorio=False,
    )
