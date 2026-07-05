"""Conversation evals: scripted (CI, no LLM) and LLM-guided (opt-in, `-m eval`)."""

import pytest

from rcm_runbook.models.session import Phase
from tests.evals.stakeholder_sim import run_llm_eval, run_scripted_eval


def test_scenario_scripted_complete(tmp_path):
    """The ground-truth scenario drives all six phases through the real tools:
    every gate goes green and the definitive export lands in the tmp dir."""
    session = run_scripted_eval(exports_dir=str(tmp_path))
    assert session.phase == Phase.P6_PLAN
    exported = list(tmp_path.glob("*.xlsx"))
    assert exported, "el export definitivo no generó ningún .xlsx"
    assert exported[0].name == "AMEF_P-101.xlsx"


@pytest.mark.eval
def test_llm_guided_session():
    """LLM-vs-LLM guided session (needs ANTHROPIC_API_KEY; run with `-m eval`)."""
    run_llm_eval()
