"""RPN arithmetic, priority bands, high-severity caveat, SAE anchors."""

import pytest

from rcm_runbook.engine.scoring import anchor_es, summarize
from rcm_runbook.models.domain import RiskScore


def score(s: int, o: int, d: int) -> RiskScore:
    return RiskScore(failure_mode_id="FM-001", severity=s, occurrence=o, detection=d)


class TestArithmetic:
    def test_rpn(self):
        assert score(8, 6, 7).rpn == 336

    def test_so(self):
        assert score(8, 6, 7).so == 48

    def test_sod_format(self):
        assert score(2, 4, 4).sod == "S2-O4-D4"


class TestPriority:
    def test_high_severity_always_critical(self):
        summary = summarize(score(9, 1, 1))  # RPN=9, tiny — but S=9
        assert "Crítica" in summary.priority_es
        assert any("SIEMPRE" in c for c in summary.caveats_es)

    def test_high_rpn_without_high_s(self):
        summary = summarize(score(7, 6, 6))  # RPN=252
        assert summary.priority_es == "Alta"

    def test_poor_detection_caveat(self):
        summary = summarize(score(5, 5, 9))
        assert any("Detección" in c for c in summary.caveats_es)

    def test_low_risk(self):
        assert summarize(score(2, 2, 2)).priority_es == "Muy baja"


class TestAnchors:
    def test_severity_anchor(self):
        assert "no funciona" in anchor_es("severidad", 8)

    def test_deteccion_accent_tolerated(self):
        assert "online" in anchor_es("detección", 1)

    def test_out_of_range(self):
        with pytest.raises(ValueError, match="entre 1 y 10"):
            anchor_es("ocurrencia", 11)

    def test_unknown_dimension(self):
        with pytest.raises(ValueError, match="Dimensión"):
            anchor_es("gravedad", 5)
