"""P0 smoke: package imports and frozen fixture integrity."""

import json
from pathlib import Path

FIXTURE = Path(__file__).parents[2] / "src" / "rcm_runbook" / "data" / "benchmark_fixture.json"


def test_package_imports() -> None:
    import rcm_runbook  # noqa: F401


def test_fixture_frozen_and_complete() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert len(fixture["amef"]["headers"]) == 27
    assert fixture["amef"]["od_npr_columns_present"] is True
    assert len(fixture["plan"]["headers"]) == 20
    assert [p["code"] for p in fixture["menu"]["policies"]] == [
        "MBC", "MBT", "OHF", "Rd", "BF", "ReP", "ExEd", "CC",
    ]
    assert len(fixture["menu"]["iso14224_failure_mode_codes"]) == 20
    assert "Mortalidad Infantil" in fixture["menu"]["failure_patterns"]
    assert "Según sea el caso" in fixture["menu"]["frequencies"]
    assert len(fixture["menu"]["disciplines"]) == 7
