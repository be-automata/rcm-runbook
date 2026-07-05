"""Unit tests for the Failure Finding Interval calculator."""

import math

import pytest

from rcm_runbook.engine.ffi import (
    HOURS_PER_YEAR,
    FFIResult,
    calculate_ffi,
    ffi_availability,
    ffi_economic,
    ffi_multi_single,
    ffi_single_multi,
    ffi_single_single,
)

Y = HOURS_PER_YEAR  # 8760 h


class TestAvailability:
    def test_u_001_mtive_10y_gives_0_2y(self):
        # FFI = 2 * 0.01 * 10y = 0.2y = 1752 h
        r = ffi_availability(mtive=10 * Y, u=0.01)
        assert r.ffi_hours == pytest.approx(1752.0)
        assert r.ffi_years == pytest.approx(0.2)
        assert r.method == "availability"
        assert r.valid

    def test_u_out_of_range(self):
        with pytest.raises(ValueError):
            ffi_availability(mtive=Y, u=0.0)
        with pytest.raises(ValueError):
            ffi_availability(mtive=Y, u=1.0)
        with pytest.raises(ValueError):
            ffi_availability(mtive=Y, u=-0.1)

    def test_mtive_nonpositive(self):
        with pytest.raises(ValueError):
            ffi_availability(mtive=0, u=0.05)


class TestSingleSingle:
    def test_hand_computed_no_sqrt(self):
        # Mtive=10y, Mted=5y, Mmf=100y -> FFI = 2*10*5/100 = 1y = 8760 h
        r = ffi_single_single(mtive=10 * Y, mted=5 * Y, mmf=100 * Y)
        assert r.ffi_hours == pytest.approx(8760.0)
        assert r.ffi_years == pytest.approx(1.0)
        assert r.ffi_months == pytest.approx(8760.0 / 730.0)
        assert r.valid

    def test_not_the_sqrt_formula(self):
        # The buggy prototype would give sqrt(2*10y*5y/100y) instead.
        r = ffi_single_single(mtive=10 * Y, mted=5 * Y, mmf=100 * Y)
        wrong = math.sqrt(2 * 10 * Y * 5 * Y / (100 * Y))
        assert r.ffi_hours != pytest.approx(wrong)

    def test_negative_input_raises(self):
        with pytest.raises(ValueError):
            ffi_single_single(mtive=-1.0, mted=Y, mmf=Y)
        with pytest.raises(ValueError):
            ffi_single_single(mtive=Y, mted=0.0, mmf=Y)
        with pytest.raises(ValueError):
            ffi_single_single(mtive=Y, mted=Y, mmf=0.0)


class TestMultiSingle:
    def test_hand_computed(self):
        # Mtive=10y, Mted_i = [5y, 10y] -> sum(1/Mted) = 0.3/y; Mmf=100y
        # FFI = 2*10 / (0.3 * 100) y = 20/30 y = 2/3 y
        r = ffi_multi_single(mtive=10 * Y, mted_list=[5 * Y, 10 * Y], mmf=100 * Y)
        assert r.ffi_years == pytest.approx(2 / 3)
        assert r.valid

    def test_single_element_matches_single_single(self):
        a = ffi_multi_single(mtive=10 * Y, mted_list=[5 * Y], mmf=100 * Y)
        b = ffi_single_single(mtive=10 * Y, mted=5 * Y, mmf=100 * Y)
        assert a.ffi_hours == pytest.approx(b.ffi_hours)

    def test_empty_list_raises(self):
        with pytest.raises(ValueError):
            ffi_multi_single(mtive=Y, mted_list=[], mmf=Y)

    def test_nonpositive_list_entry_raises(self):
        with pytest.raises(ValueError):
            ffi_multi_single(mtive=Y, mted_list=[Y, -5.0], mmf=Y)


class TestSingleMulti:
    def test_n1_reduces_exactly_to_single_single(self):
        # (n+1)*Mted/Mmf at n=1 -> 2*Mted/Mmf, times Mtive ** 1/1
        multi = ffi_single_multi(mtive=10 * Y, mted=5 * Y, mmf=100 * Y, n=1)
        single = ffi_single_single(mtive=10 * Y, mted=5 * Y, mmf=100 * Y)
        assert multi.ffi_hours == single.ffi_hours  # exact equality required

    def test_hand_computed_n2(self):
        # Mtive=2y, Mted=3y, Mmf=100y, n=2:
        # FFI = 2y * (3*3/100)^(1/2) = 2y * 0.3 = 0.6y
        r = ffi_single_multi(mtive=2 * Y, mted=3 * Y, mmf=100 * Y, n=2)
        assert r.ffi_years == pytest.approx(0.6)
        assert r.valid

    def test_n_must_be_integer_ge_1(self):
        with pytest.raises(ValueError):
            ffi_single_multi(mtive=Y, mted=Y, mmf=Y, n=0)
        with pytest.raises(ValueError):
            ffi_single_multi(mtive=Y, mted=Y, mmf=Y, n=2.5)  # type: ignore[arg-type]

    def test_nonpositive_times_raise(self):
        with pytest.raises(ValueError):
            ffi_single_multi(mtive=Y, mted=Y, mmf=-1.0, n=2)


class TestEconomic:
    def test_hand_computed_sqrt(self):
        # Mtive=2000h, Mted=1000h, Cff=25, Cmf=100:
        # FFI = sqrt(2*2000*1000*25/100) = sqrt(1_000_000) = 1000h
        r = ffi_economic(mtive=2000.0, mted=1000.0, cmf=100.0, cff=25.0)
        assert r.ffi_hours == pytest.approx(1000.0)
        assert "sqrt" in r.formula
        assert r.valid

    def test_nonpositive_costs_raise(self):
        with pytest.raises(ValueError):
            ffi_economic(mtive=Y, mted=Y, cmf=0.0, cff=10.0)
        with pytest.raises(ValueError):
            ffi_economic(mtive=Y, mted=Y, cmf=100.0, cff=-10.0)


class TestWarnings:
    def test_ffi_exceeding_mtive_warns(self):
        # Mtive=1y, Mted=10y, Mmf=10y -> FFI = 2*1*10/10 = 2y > Mtive
        r = ffi_single_single(mtive=1 * Y, mted=10 * Y, mmf=10 * Y)
        assert not r.valid
        assert any("exceeds the protective device MTBF" in w for w in r.warnings)

    def test_ffi_below_24h_warns(self):
        # FFI = 2 * 0.001 * 1000h = 2h < 24h
        r = ffi_availability(mtive=1000.0, u=0.001)
        assert not r.valid
        assert any("24 h" in w for w in r.warnings)

    def test_clean_result_has_no_warnings(self):
        r = ffi_single_single(mtive=10 * Y, mted=5 * Y, mmf=100 * Y)
        assert r.warnings == []
        assert r.valid


class TestDispatcher:
    def test_dispatch_each_method(self):
        cases = {
            "availability": {"mtive": 10 * Y, "u": 0.01},
            "single_single": {"mtive": 10 * Y, "mted": 5 * Y, "mmf": 100 * Y},
            "multi_single": {"mtive": 10 * Y, "mted_list": [5 * Y], "mmf": 100 * Y},
            "single_multi": {"mtive": 10 * Y, "mted": 5 * Y, "mmf": 100 * Y, "n": 2},
            "economic": {"mtive": 2000.0, "mted": 1000.0, "cmf": 100000.0, "cff": 25.0},
        }
        for method, params in cases.items():
            result = calculate_ffi(method, params)
            assert isinstance(result, FFIResult)
            assert result.method == method
            assert result.ffi_hours > 0

    def test_dispatch_matches_direct_call(self):
        via_dispatch = calculate_ffi(
            "single_single", {"mtive": 10 * Y, "mted": 5 * Y, "mmf": 100 * Y}
        )
        direct = ffi_single_single(mtive=10 * Y, mted=5 * Y, mmf=100 * Y)
        assert via_dispatch.ffi_hours == direct.ffi_hours

    def test_unknown_method_raises(self):
        with pytest.raises(ValueError, match="Unknown FFI method"):
            calculate_ffi("bogus", {"mtive": Y})
