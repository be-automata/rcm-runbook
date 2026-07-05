"""Extract the client AMEF benchmark (.xls, BIFF) structure into a frozen JSON fixture.

The fixture (src/rcm_runbook/data/benchmark_fixture.json) is the single
published-language contract between the client's Excel dialect and the domain:
catalogs.py loads controlled vocabularies from it and the export golden tests
assert against it. Run once at P0 (and again only if the client ships a new
benchmark):

    uv run python scripts/extract_benchmark.py data/reference/amef_benchmark.xls
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import xlrd

FIXTURE_PATH = (
    Path(__file__).parent.parent / "src" / "rcm_runbook" / "data" / "benchmark_fixture.json"
)

AMEF_HEADER_ROW = 12  # 0-indexed row of the AMEF sheet column headers
PLAN_HEADER_ROW = 11  # 0-indexed row of the PLAN DE MANTENIMIENTO column headers


def _row(sheet: xlrd.sheet.Sheet, r: int) -> list[str]:
    return [str(sheet.cell_value(r, c)).strip() for c in range(sheet.ncols)]


def _nonempty(values: list[str]) -> list[str]:
    return [v for v in values if v]


def _column_block(sheet: xlrd.sheet.Sheet, header_row: int, col: int) -> list[str]:
    """Read a vertical vocabulary list under `header_row` in column `col` until blank."""
    out: list[str] = []
    for r in range(header_row + 1, sheet.nrows):
        v = str(sheet.cell_value(r, col)).strip()
        if not v:
            break
        out.append(v)
    return out


def extract(xls_path: Path) -> dict:
    book = xlrd.open_workbook(str(xls_path), formatting_info=False)

    amef = book.sheet_by_name("AMEF")
    plan = book.sheet_by_name("PLAN DE MANTENIMIENTO")
    sae = book.sheet_by_name("SAE-J1739")
    menu = book.sheet_by_name("MENU")

    amef_headers = _nonempty(_row(amef, AMEF_HEADER_ROW))
    plan_headers = _nonempty(_row(plan, PLAN_HEADER_ROW))

    # AMEF sheet has no Ocurrencia / Detección / NPR columns (verified against headers)
    od_npr_present = any(
        h.lower().startswith(("ocurrencia", "detecci", "npr")) for h in amef_headers
    )

    # MENU vocabularies. Verified layout (0-indexed cols):
    #   c1/c2: Característica de falla (R5-R8); Política de Mantenimiento code/label (R14-R21);
    #          Puestos de trabajo / disciplines (R26+)
    #   c4:    EfectoLocal list (R5+); "Frecuencia" header at R18 then frequency list (R19+)
    #   c8-10: Codigo ISO 14224 (codigo | definicion | descripcion), R6+
    failure_patterns: list[str] = []
    policies: list[dict] = []
    effect_locals: list[str] = []
    frequencies: list[str] = []
    iso_codes: list[dict] = []
    disciplines: list[str] = []

    section = None
    for r in range(menu.nrows):
        c1 = str(menu.cell_value(r, 1)).strip()
        c2 = str(menu.cell_value(r, 2)).strip()
        # ISO codes table (c8-c10) spans rows shared with other sections — extract first,
        # before any section `continue`
        code = str(menu.cell_value(r, 8)).strip() if menu.ncols > 8 else ""
        defin = str(menu.cell_value(r, 9)).strip() if menu.ncols > 9 else ""
        desc = str(menu.cell_value(r, 10)).strip() if menu.ncols > 10 else ""
        if code and defin and code != "Codigo":
            iso_codes.append({"code": code, "definition": defin, "description": desc})
        if c1 == "Característica de falla":
            section = "patterns"
            continue
        if c1 == "Política de Mantenimiento":
            section = "policies"
            continue
        if c1 == "Puestos de trabajo":
            section = "disciplines"
            continue
        if c1 == "Familia de Equipo":
            section = None
            continue
        if section == "patterns":
            if c1:
                failure_patterns.append(c1)
            elif failure_patterns:
                section = None
        elif section == "policies" and c1 and c2:
            policies.append({"code": c1, "label": c2})
        elif section == "disciplines" and c1:
            disciplines.append(c1)

    # EfectoLocal list and frequency list both live in c4
    for r in range(menu.nrows):
        v = str(menu.cell_value(r, 4)).strip()
        if v == "EfectoLocal":
            effect_locals = _column_block(menu, r, 4)
        if v == "Frecuencia":
            frequencies = _column_block(menu, r, 4)
            break

    # SAE-J1739 S/O/D tables: three blocks (severity table 1, occurrence table 2, detection table 3)
    sae_rows = []
    for r in range(sae.nrows):
        vals = [str(sae.cell_value(r, c)).strip() for c in range(min(sae.ncols, 3))]
        if any(vals):
            sae_rows.append(vals)

    fixture = {
        "source_file": xls_path.name,
        "sheets": [s.name for s in book.sheets()],
        "amef": {
            "header_row_excel": AMEF_HEADER_ROW + 1,
            "title_rows": {str(r + 1): _nonempty(_row(amef, r)) for r in range(AMEF_HEADER_ROW)},
            "headers": amef_headers,
            "od_npr_columns_present": od_npr_present,
        },
        "plan": {
            "header_row_excel": PLAN_HEADER_ROW + 1,
            "title_rows": {str(r + 1): _nonempty(_row(plan, r)) for r in range(PLAN_HEADER_ROW)},
            "headers": plan_headers,
        },
        "menu": {
            "failure_patterns": failure_patterns,
            "policies": policies,
            "effect_locals": effect_locals,
            "frequencies": frequencies,
            "iso14224_failure_mode_codes": iso_codes,
            "disciplines": disciplines,
        },
        "sae_j1739_rows": sae_rows,
    }
    return fixture


def main() -> None:
    xls = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/reference/amef_benchmark.xls")
    fixture = extract(xls)
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fixture written: {FIXTURE_PATH}")
    print(f"AMEF headers ({len(fixture['amef']['headers'])}): {fixture['amef']['headers']}")
    print(f"PLAN headers ({len(fixture['plan']['headers'])}): {fixture['plan']['headers']}")
    print(f"O/D/NPR columns present in AMEF: {fixture['amef']['od_npr_columns_present']}")
    print(f"Patterns: {fixture['menu']['failure_patterns']}")
    print(f"Policies: {[p['code'] for p in fixture['menu']['policies']]}")
    print(f"Frequencies: {fixture['menu']['frequencies']}")
    print(f"ISO codes: {[c['code'] for c in fixture['menu']['iso14224_failure_mode_codes']]}")


if __name__ == "__main__":
    main()
