"""Excel deliverable builder — proyección casi pura.

La única regla de negocio que conoce esta capa es si un intervalo de búsqueda de
fallas sigue aplicando, y la comparte con la compuerta a propósito
(`compliance.sigue_necesitando_busqueda_de_fallas`): tener dos reglas separadas
las hacía divergir dentro del mismo libro.

Builds the workbook from the frozen benchmark fixture (title block, header row,
lookup dropdowns, SAE reference sheet) and appends AMEF/PLAN rows. The gate
check (`compliance.export_blockers`) is application-layer orchestration in
agent/tools.py — never here.
"""

from __future__ import annotations

import re
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation
from openpyxl.worksheet.worksheet import Worksheet

from rcm_runbook.engine.compliance import (
    export_blockers,
    sigue_necesitando_busqueda_de_fallas,
)
from rcm_runbook.export.rows import (
    amef_headers,
    amef_rows_with_ids,
    plan_headers,
    plan_rows_with_ids,
    rutas_inconsistentes,
)
from rcm_runbook.models.catalogs import (
    METODOS_FFI_ES,
    POLICY_LABELS_ES,
    SAE_DETECTION_ES,
    SAE_OCCURRENCE_ES,
    SAE_SEVERITY_ES,
    MaintenancePolicy,
    fixture,
)
from rcm_runbook.models.session import RCMSession

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=9)
TITLE_FONT = Font(bold=True, size=14)
THIN = Side(style="thin", color="9E9E9E")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

# Header rows come from the frozen fixture (benchmark: AMEF!13, PLAN!12 in Excel terms)
AMEF_HEADER_ROW = fixture().amef.header_row_excel
PLAN_HEADER_ROW = fixture().plan.header_row_excel
LOOKUPS_SHEET = "LOOKUPS"


ID_HEADER = "ID"
DRAFT_STAMP = "BORRADOR — NO APTO PARA EJECUCIÓN"


HEADER_ALIGN = Alignment(wrap_text=True, vertical="center", horizontal="center")


def _write_id_header(ws: Worksheet, header_row: int) -> None:
    """El `FM-id` en la columna A, que queda fuera del rango del benchmark.

    No puede ir como campo del modelo de fila (rompería el contrato verbatim de
    encabezados), y no hay otra columna libre. La A además queda fija por
    `freeze_panes`, así que el identificador acompaña al lector mientras recorre
    las 27 columnas — que es justo lo que hace falta para cruzar el libro con la
    conversación, donde el agente cita los modos por su código.
    """
    cell = ws.cell(row=header_row, column=1, value=ID_HEADER)
    cell.fill = HEADER_FILL
    cell.font = HEADER_FONT
    cell.border = BORDER
    cell.alignment = HEADER_ALIGN
    ws.column_dimensions["A"].width = 12


def _write_id_cell(ws: Worksheet, row: int, fmid: str) -> None:
    """El id se escribe DENTRO del bucle de datos, no en una pasada aparte.

    Dos bucles sobre las mismas filas con la misma aritmética se desincronizan
    en silencio: bastaría cambiar un `start` para que cada id quedara junto a la
    fila del modo siguiente, y un entregable que miente sobre qué fila es cuál
    es peor que uno sin identificadores.
    """
    cell = ws.cell(row=row, column=1, value=fmid)
    cell.border = BORDER
    cell.alignment = Alignment(vertical="top")


def _write_title_block(
    ws: Worksheet, session: RCMSession, title: str, draft: bool = False
) -> None:
    ws.cell(row=2, column=2, value=title).font = TITLE_FONT
    if draft:
        # El prefijo BORRADOR_ del nombre del fichero no viaja con la captura de
        # pantalla, ni con la fila pegada en un correo, ni con la hoja impresa.
        # El interesado revisó un borrador creyéndolo terminado; el sello va
        # dentro del libro.
        sello = ws.cell(row=2, column=5, value=DRAFT_STAMP)
        sello.font = Font(bold=True, size=12, color="C00000")
    meta = [
        ("CAMPO:", session.scope.location),
        ("APLICACION:", session.scope.normal_conditions),
        ("TAG:", session.scope.tag),
        ("UBICACION:", session.scope.location),
        ("OBJETIVO:", session.scope.objective),
    ]
    for i, (label, value) in enumerate(meta, start=4):
        ws.cell(row=i, column=2, value=label).font = Font(bold=True, size=9)
        ws.cell(row=i, column=4, value=value)


def _write_headers(ws: Worksheet, headers: list[str], header_row: int) -> None:
    for col, header in enumerate(headers, start=2):
        cell = ws.cell(row=header_row, column=col, value=header)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.border = BORDER
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        ws.column_dimensions[get_column_letter(col)].width = 18
    ws.freeze_panes = ws.cell(row=header_row + 1, column=2)


def _write_lookups(wb: Workbook) -> dict[str, str]:
    """Hidden lookups sheet feeding dropdowns; returns column ranges per vocabulary."""
    fx = fixture()
    ws = wb.create_sheet(LOOKUPS_SHEET)
    vocabularies: dict[str, list[str]] = {
        "patterns": fx.menu.failure_patterns,
        "policies": [p.code for p in fx.menu.policies],
        "frequencies": fx.menu.frequencies,
        "disciplines": fx.menu.disciplines,
        "iso_codes": [c.code for c in fx.menu.iso14224_failure_mode_codes],
        "si_no": ["SI", "NO"],
        "marca": ["X", ""],
        # Al FINAL a propósito: cada clave es una columna de LOOKUPS y las
        # validaciones apuntan a columnas concretas — meterla en medio desplazó
        # los códigos ISO y habría roto los desplegables del libro del cliente.
        #
        # El código sigue solo en `policies` porque la validación de la columna
        # del AMEF apunta ahí y es el formato del benchmark. Pero la etiqueta
        # venía en el fixture y se tiraba: quien abre el libro veía «Rd» y
        # «ExEd» sin nada que los explicara en ninguna hoja.
        "policies_es": [f"{p.code} — {p.label}" for p in fx.menu.policies],
    }
    ranges: dict[str, str] = {}
    for col, (name, values) in enumerate(vocabularies.items(), start=1):
        ws.cell(row=1, column=col, value=name)
        for row, value in enumerate(values, start=2):
            ws.cell(row=row, column=col, value=value)
        letter = get_column_letter(col)
        ranges[name] = f"{LOOKUPS_SHEET}!${letter}$2:${letter}${len(values) + 1}"
    ws.sheet_state = "hidden"
    return ranges


def _add_validation(
    ws: Worksheet, headers: list[str], header_row: int, ranges: dict[str, str],
    column_vocab: dict[str, str], max_row: int,
) -> None:
    for header, vocab in column_vocab.items():
        if header not in headers:
            continue
        col = headers.index(header) + 2
        letter = get_column_letter(col)
        dv = DataValidation(type="list", formula1=f"={ranges[vocab]}", allow_blank=True)
        dv.error = "Valor fuera del catálogo del cliente (hoja MENU)."
        dv.errorTitle = "Valor inválido"
        ws.add_data_validation(dv)
        dv.add(f"{letter}{header_row + 1}:{letter}{max(max_row, header_row + 30)}")


AMEF_COLUMN_VOCAB = {
    "Codigo ISO 14224": "iso_codes",
    "Patrón de Falla": "patterns",
    "Estrategia de Mantenimiento": "policies",
    "FRECUENCIA DE LA TAREA": "frequencies",
    "EJECUTOR (DISCIPLINA)": "disciplines",
    "REQUIERE PARO DEL EQUIPO?": "si_no",
    "Seguridad": "marca",
    "Ambiente": "marca",
    "Operacional": "marca",
    "No Operacional": "marca",
}

PLAN_COLUMN_VOCAB = {
    "Codigo ISO 14224": "iso_codes",
    "Patrón de Falla": "patterns",
    "FRECUENCIA DE LA TAREA": "frequencies",
    "EJECUTOR (DISCIPLINA)": "disciplines",
    "REQUIERE PARO DEL EQUIPO?": "si_no",
    "Basado en Condición": "marca",
    "Preventivo": "marca",
    "Detección de Fallas": "marca",
    "Otros tipos de Estrategias (Rediseño, etc).": "marca",
    "Seguridad": "marca",
    "Ambiente": "marca",
    "Operacional": "marca",
    "No Operacional": "marca",
}


def _write_sae_sheet(wb: Workbook) -> None:
    ws = wb.create_sheet("SAE-J1739")
    ws.cell(row=1, column=2, value="SAE J1739 — Criterios de valoración").font = TITLE_FONT
    ws.cell(row=2, column=2, value="RPN = Severidad × Ocurrencia × Detección")
    row = 4
    for title, table in (
        ("TABLA 1 — SEVERIDAD", SAE_SEVERITY_ES),
        ("TABLA 2 — OCURRENCIA", SAE_OCCURRENCE_ES),
        ("TABLA 3 — DETECCIÓN", SAE_DETECTION_ES),
    ):
        ws.cell(row=row, column=2, value=title).font = Font(bold=True, size=11)
        row += 1
        for rank in sorted(table, reverse=True):
            ws.cell(row=row, column=2, value=rank)
            ws.cell(row=row, column=3, value=table[rank]).alignment = WRAP
            row += 1
        row += 1
    ws.column_dimensions["C"].width = 90


def _write_audit_sheet(
    wb: Workbook, session: RCMSession, blockers: list[str] | None = None
) -> None:
    """JA1011 audit trail: discards, HITL ledger, decision justifications, residual risk."""
    ws = wb.create_sheet("AUDITORIA RCM")
    ws.cell(row=1, column=1, value="Registro de auditoría JA1011").font = TITLE_FONT
    row = 3

    # Los defectos viajan CON el entregable. Antes el borrador se llevaba el
    # estado y dejaba los bloqueadores atrás, así que un análisis a medias salía
    # con cara de terminado. El FM-id va en su propia celda para que se pueda
    # localizar la fila —y para que un test lo pueda afirmar sin leer prosa.
    if blockers:
        ws.cell(row=row, column=1, value="Defectos que impiden el entregable definitivo").font = (
            Font(bold=True)
        )
        row += 1
        for blocker in blockers:
            # `findall` y no `search`: un bloqueador que relacione dos modos
            # —los duplicados, por ejemplo— dejaría a uno de los dos sin forma
            # de localizarlo. Hoy ninguno de los 121 trae más de un id, así que
            # con `search` acertaba por el orden de las palabras, no por diseño.
            marcas = dict.fromkeys(re.findall(r"\b(?:FM|FF)-\d+", blocker))
            ws.cell(row=row, column=1, value="; ".join(marcas))
            # La prosa va a la columna C, que es la ancha de esta hoja (70) y la
            # que usan las demás secciones. En la B (14) los 121 bloqueadores de
            # ~95 caracteres salían ilegibles.
            ws.cell(row=row, column=3, value=blocker).alignment = WRAP
            row += 1
        row += 1

    desacuerdos = rutas_inconsistentes(session)
    if desacuerdos:
        ws.cell(
            row=row, column=1,
            value="Rutas guardadas que no coinciden con la lógica de decisión",
        ).font = Font(bold=True)
        row += 1
        for fmid, guardada, calculada in desacuerdos:
            ws.cell(row=row, column=1, value=fmid)
            ws.cell(
                row=row, column=3,
                value=f"guardada: {guardada} — contraste: {calculada}. "
                      "No se imprime ninguna en la fila; hay que rehacer la decisión.",
            ).alignment = WRAP
            row += 1
        row += 1
    ws.cell(row=row, column=1, value="Modos descartados por no credibilidad").font = Font(bold=True)
    row += 1
    for fm in session.failure_modes.values():
        if not fm.credible:
            ws.cell(row=row, column=1, value=fm.id)
            ws.cell(row=row, column=2, value=fm.description)
            ws.cell(row=row, column=3, value=fm.non_credible_discard)
            row += 1
    row += 1
    ws.cell(row=row, column=1, value="Confirmaciones humanas (HITL)").font = Font(bold=True)
    row += 1
    for rec in session.hitl_ledger:
        ws.cell(row=row, column=1, value=rec.failure_mode_id)
        ws.cell(row=row, column=2, value=rec.reason)
        ws.cell(row=row, column=3, value=rec.confirmed_by or "PENDIENTE")
        row += 1
    row += 1
    ws.cell(row=row, column=1, value="Justificación de decisiones y riesgo residual").font = (
        Font(bold=True)
    )
    row += 1
    for fmid, decision in session.decisions.items():
        initial = session.risk_scores.get(fmid)
        residual = session.residual_scores.get(fmid)
        ws.cell(row=row, column=1, value=fmid)
        # Con su nombre: esta hoja es la del expediente, no la del benchmark, y
        # la fila «Nomenclatura» está treinta filas más arriba en esta misma
        # hoja glosando las siglas del FFI mientras esta columna iba pelada.
        nombre_politica = POLICY_LABELS_ES.get(MaintenancePolicy(decision.policy), "")
        ws.cell(
            row=row, column=2,
            value=f"{decision.policy} ({nombre_politica})" if nombre_politica
            else decision.policy,
        )
        ws.cell(row=row, column=3, value=decision.justification).alignment = WRAP
        ws.cell(row=row, column=4, value=initial.sod if initial else "")
        ws.cell(row=row, column=5, value=f"RPN {initial.rpn}" if initial else "")
        ws.cell(row=row, column=6, value=residual.sod if residual else "")
        ws.cell(row=row, column=7, value=f"RPN residual {residual.rpn}" if residual else "")
        row += 1
    row += 1
    ws.cell(row=row, column=1, value="TPEF / frecuencia de fallas (tabla completa)").font = (
        Font(bold=True)
    )
    row += 1
    for fmid, fm in session.failure_modes.items():
        if fm.tpef is None or not fm.credible:
            continue
        ws.cell(row=row, column=1, value=fmid)
        ws.cell(row=row, column=2, value=f"{fm.tpef.value_hours:.0f} h")
        ws.cell(row=row, column=3, value=f"{fm.tpef.value_years:.2f} años")
        ws.cell(row=row, column=4, value=fm.tpef.fuente)
        ws.cell(row=row, column=5, value=fm.tpef.note)
        row += 1
    # Cinco datos que las compuertas exigen y que no llegaban a ninguna hoja: se
    # entrevistaba al cliente por ellos, se bloqueaba el entregable hasta
    # tenerlos, y luego se tiraban. Van aquí, que es la hoja del expediente.
    row += 1
    ws.cell(row=row, column=1, value="Intervalo de búsqueda de fallas (FFI) calculado").font = (
        Font(bold=True)
    )
    row += 1
    if session.ffi_por_modo:
        # Quien abre esta hoja es el ingeniero de mantenimiento, no el modelo:
        # `Mtive`/`Mted`/`Mmf` estaban definidos con esmero en el docstring de la
        # herramienta y en el motor, y en ninguna parte del entregable.
        ws.cell(row=row, column=1, value="Nomenclatura:")
        ws.cell(
            row=row, column=2,
            value="TPEF = Tiempo Promedio Entre Fallas · Mtive = TPEF del "
                  "dispositivo de protección · Mted = TPEF de la función protegida · "
                  "Mmf = TPEF tolerado de la falla múltiple",
        ).alignment = WRAP
        row += 1
    for fmid, ffi in session.ffi_por_modo.items():
        # Los que ya no aplican se ANOTAN, no se esconden. Filtrarlos dejaba una
        # sección con su cabecera y su nomenclatura y cero filas —definiciones
        # sin término— y, peor, hacía desaparecer del entregable un intervalo
        # que sí se calculó, sin decirlo. Es el mismo descarte silencioso un
        # piso más arriba.
        vigente = sigue_necesitando_busqueda_de_fallas(session, fmid)
        ws.cell(row=row, column=1, value=fmid)
        ws.cell(row=row, column=2, value=round(ffi.horas, 1))
        ws.cell(row=row, column=3, value=f"{ffi.horas / 730.0:.1f} meses")
        # Con su significado: `single_single` crudo y en inglés es una sigla
        # pelada más, y estaba justo debajo de la fila que existe para
        # definirlas.
        ws.cell(row=row, column=4, value=METODOS_FFI_ES.get(ffi.metodo, ffi.metodo))
        ws.cell(row=row, column=5, value=ffi.formula)
        # Qué tarea dice ejecutar este intervalo, y cada cuánto. Quién marca esa
        # fila es el modelo, y ninguna comprobación determinista puede saber si
        # marcó la correcta: se vio marcar una limpieza diaria y dejar la prueba
        # funcional real a «Parada de Planta». Lo que sí se puede es ponerlo
        # delante de quien revisa, para que un disparate se vea.
        marcadas = [
            f"{t.description} ({t.frequency})"
            for t in session.tasks.get(fmid, [])
            if t.es_busqueda_de_fallas
        ]
        ws.cell(
            row=row, column=6,
            value=(
                "Ejecutado por: " + ("; ".join(marcadas) if marcadas
                                     else "NINGUNA TAREA MARCADA")
                if vigente
                else "YA NO APLICA: el modo dejó de requerir búsqueda de fallas "
                     "(efecto evidente, operar-hasta-la-falla o descartado)"
            ),
        ).alignment = WRAP
        ws.cell(row=row, column=7, value="; ".join(ffi.avisos)).alignment = WRAP
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Acciones recomendadas").font = Font(bold=True)
    row += 1
    for fmid, acciones in session.actions.items():
        for accion in acciones:
            ws.cell(row=row, column=1, value=fmid)
            ws.cell(row=row, column=2, value=accion.what).alignment = WRAP
            ws.cell(row=row, column=3, value=accion.who)
            ws.cell(row=row, column=4, value=accion.when)
            ws.cell(row=row, column=5, value=accion.verification)
            ws.cell(row=row, column=6, value=accion.resources)
            row += 1

    row += 1
    ws.cell(row=row, column=1, value="Equipo multidisciplinario").font = Font(bold=True)
    row += 1
    for miembro in session.team:
        ws.cell(row=row, column=1, value=miembro.name)
        ws.cell(row=row, column=2, value=miembro.role)
        row += 1

    # Leyenda de políticas en la hoja VISIBLE. Ponerla solo en LOOKUPS no servía
    # de nada: esa hoja es `sheet_state="hidden"`, así que el comentario decía
    # «quien abre el libro veía Rd y ExEd sin nada que los explicara» y seguía
    # sin verlo. En LOOKUPS se queda igualmente, para quien la desoculte.
    row += 1
    ws.cell(row=row, column=1, value="Políticas de mantenimiento").font = Font(bold=True)
    row += 1
    for politica, nombre in POLICY_LABELS_ES.items():
        ws.cell(row=row, column=1, value=politica.value)
        ws.cell(row=row, column=2, value=nombre)
        row += 1

    row += 1
    ws.cell(row=row, column=1, value="Gobernanza del plan").font = Font(bold=True)
    row += 1
    for kpi in session.kpis:
        # `str(kpi)` sobre un BaseModel escribe el repr de Python en la celda del
        # cliente: «name='MTBF' target='> 17.520 h'». Era el único de los cinco
        # elementos de gobernanza sin formatear, y el único sin test.
        ws.cell(row=row, column=1, value="KPI")
        ws.cell(row=row, column=2, value=kpi.name)
        ws.cell(row=row, column=3, value=kpi.target).alignment = WRAP
        row += 1
    for disparador in session.review_triggers:
        ws.cell(row=row, column=1, value="Disparador de revisión")
        ws.cell(row=row, column=3, value=disparador).alignment = WRAP
        row += 1
    ws.cell(row=row, column=1, value="Validación / aprobación")
    ws.cell(row=row, column=3, value=session.validation_signoff).alignment = WRAP
    row += 1

    for col, width in (("A", 10), ("B", 14), ("C", 70), ("D", 12), ("E", 12), ("F", 12), ("G", 16)):
        ws.column_dimensions[col].width = width


def build_workbook(
    session: RCMSession, draft: bool = False, blockers: list[str] | None = None
) -> Workbook:
    wb = Workbook()
    amef_ws = wb.active
    amef_ws.title = "AMEF"
    plan_ws = wb.create_sheet("PLAN DE MANTENIMIENTO")
    ranges = _write_lookups(wb)

    _write_title_block(
        amef_ws, session, "ANALISIS DE MODOS Y EFECTOS DE FALLAS", draft=draft
    )
    headers_a = amef_headers()
    _write_headers(amef_ws, headers_a, AMEF_HEADER_ROW)
    amef_pairs = amef_rows_with_ids(session)
    _write_id_header(amef_ws, AMEF_HEADER_ROW)
    for r, (fmid, row_model) in enumerate(amef_pairs, start=AMEF_HEADER_ROW + 1):
        _write_id_cell(amef_ws, r, fmid)
        for c, value in enumerate(row_model.model_dump(by_alias=True).values(), start=2):
            cell = amef_ws.cell(row=r, column=c, value=value)
            cell.border = BORDER
            cell.alignment = WRAP
    _add_validation(amef_ws, headers_a, AMEF_HEADER_ROW, ranges, AMEF_COLUMN_VOCAB,
                    AMEF_HEADER_ROW + len(amef_pairs))

    _write_title_block(plan_ws, session, "PLAN DE MANTENIMIENTO", draft=draft)
    headers_p = plan_headers()
    _write_headers(plan_ws, headers_p, PLAN_HEADER_ROW)
    plan_pairs = plan_rows_with_ids(session)
    _write_id_header(plan_ws, PLAN_HEADER_ROW)
    for r, (fmid, plan_model) in enumerate(plan_pairs, start=PLAN_HEADER_ROW + 1):
        _write_id_cell(plan_ws, r, fmid)
        for c, value in enumerate(plan_model.model_dump(by_alias=True).values(), start=2):
            cell = plan_ws.cell(row=r, column=c, value=value)
            cell.border = BORDER
            cell.alignment = WRAP
    _add_validation(plan_ws, headers_p, PLAN_HEADER_ROW, ranges, PLAN_COLUMN_VOCAB,
                    PLAN_HEADER_ROW + len(plan_pairs))

    # TPEF / frequency-of-failure block on PLAN title area (benchmark layout).
    # Bounded strictly above the header row — the full table lives in AUDITORIA RCM.
    tpef_row = 4
    tpef_cell = plan_ws.cell(row=tpef_row, column=14, value="FRECUENCIA DE FALLAS (TPEF)")
    tpef_cell.font = Font(bold=True, size=9)
    r = tpef_row + 1
    max_tpef_row = PLAN_HEADER_ROW - 2
    tpef_modes = [
        (fmid, fm) for fmid, fm in session.failure_modes.items()
        if fm.tpef is not None and fm.credible
    ]
    # Si no entran todos, la ÚLTIMA fila se reserva para el aviso. Antes se
    # escribía encima de una fila ya poblada: pisaba su FM- y dejaba sus horas,
    # años y fuente sin el modo al que pertenecen — datos huérfanos que se leen
    # como si fueran del propio renglón «ver AUDITORIA».
    caben = max_tpef_row - r + 1
    visibles = tpef_modes[: caben - 1] if len(tpef_modes) > caben else tpef_modes
    for fmid, fm in visibles:
        assert fm.tpef is not None
        plan_ws.cell(row=r, column=14, value=fmid)
        plan_ws.cell(row=r, column=15, value=f"{fm.tpef.value_hours:.0f} h")
        plan_ws.cell(row=r, column=16, value=f"{fm.tpef.value_years:.2f} años")
        plan_ws.cell(row=r, column=17, value=fm.tpef.fuente)
        r += 1
    if len(visibles) < len(tpef_modes):
        plan_ws.cell(row=max_tpef_row, column=14,
                     value="… ver hoja AUDITORIA RCM (tabla TPEF completa)")

    _write_sae_sheet(wb)
    _write_audit_sheet(wb, session, blockers=blockers)
    return wb


def safe_export_name(tag: str) -> str:
    """Filename-safe tag matching the /exports route charset ([\\w.\\-] only)."""
    cleaned = re.sub(r"[^\w.\-]+", "_", tag.strip()) or "SIN-TAG"
    return cleaned.strip("._-") or "SIN-TAG"


def export_xlsx(
    session: RCMSession,
    output_dir: str | Path,
    session_id: str = "",
    draft: bool = False,
    blockers: list[str] | None = None,
) -> Path:
    """Write the deliverable under a per-session subdirectory (no cross-session
    overwrites; the download route scopes by session_id). Drafts are visually
    distinct in three places: the `BORRADOR_` filename prefix, a stamp in the
    title block of both sheets, and the list of blockers on AUDITORIA RCM — a
    borrador must never pass for el entregable definitivo.

    `blockers` se calcula acá si no lo pasan, para que ningún camino de
    exportación pueda producir un borrador sin sus defectos adjuntos.
    """
    out_dir = Path(output_dir)
    if session_id:
        out_dir = out_dir / safe_export_name(session_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    tag = safe_export_name(session.scope.tag or "SIN-TAG")
    prefix = "BORRADOR_AMEF" if draft else "AMEF"
    path = out_dir / f"{prefix}_{tag}.xlsx"
    if draft and blockers is None:
        blockers = export_blockers(session)
    build_workbook(session, draft=draft, blockers=blockers).save(path)
    return path
