"""Failure Finding Interval (FFI) calculator.

Formulas re-derived from the RCM Handbook (rcm-handbook.com, "Failure
Finding Intervals"), cross-checked against the reference calculator
workbook variable definitions.

FFI applies ONLY to hidden failure modes of protective devices: failures
that are not evident to the operating crew under normal circumstances and
are only revealed by a scheduled failure-finding task (or by a demand on
the protection). It is not applicable to evident failure modes.

Terms (all times in consistent units, hours by default):
    Mtive  Mean time between failures of the protecTIVE device.
    Mted   Mean time between failures of the protecTED function/device.
    Mmf    Acceptable mean time between multiple failures (both the
           protective device and the protected function have failed).
           NOTE: choosing an acceptable Mmf for safety- or
           environment-consequence multiple failures is a risk-acceptance
           judgement and MUST remain a human-in-the-loop (HITL) decision;
           this module only computes intervals from a given Mmf.
    U      Acceptable fraction of time protection is unavailable (0..1).
    n      Number of redundant protective devices.
    Cmf    Cost of a multiple failure.
    Cff    Cost of performing one failure-finding task.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

HOURS_PER_YEAR = 8760.0
HOURS_PER_MONTH = 730.0

#: FFI shorter than this is flagged as impractically frequent.
MIN_PRACTICAL_FFI_HOURS = 24.0


@dataclass(frozen=True)
class FFIResult:
    """Outcome of a failure finding interval calculation."""

    method: str
    ffi_hours: float
    ffi_months: float
    ffi_years: float
    formula: str
    inputs: dict[str, Any]
    warnings: list[str] = field(default_factory=list)
    valid: bool = True


def _require_positive(**values: float) -> None:
    for name, value in values.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"{name} must be a number, got {value!r}")
        if value <= 0:
            raise ValueError(f"{name} must be > 0, got {value}")


def _build_result(
    method: str,
    ffi_hours: float,
    formula: str,
    inputs: dict[str, Any],
    mtive: float,
) -> FFIResult:
    warnings: list[str] = []
    if ffi_hours > mtive:
        warnings.append(
            f"Computed FFI ({ffi_hours:.1f} h) exceeds the protective device MTBF "
            f"(Mtive={mtive:.1f} h); the interval is suspect - review inputs."
        )
    if ffi_hours < MIN_PRACTICAL_FFI_HOURS:
        warnings.append(
            f"Computed FFI ({ffi_hours:.1f} h) is shorter than 24 h; failure finding "
            "this frequent is usually impractical - consider redesign."
        )
    return FFIResult(
        method=method,
        ffi_hours=ffi_hours,
        ffi_months=ffi_hours / HOURS_PER_MONTH,
        ffi_years=ffi_hours / HOURS_PER_YEAR,
        formula=formula,
        inputs=inputs,
        warnings=warnings,
        valid=not warnings,
    )


def ffi_availability(mtive: float, u: float) -> FFIResult:
    """Availability-based FFI: FFI = 2 * U * Mtive.

    ``u`` is the acceptable unavailability fraction of the protective
    device (e.g. 0.02 for 2% downtime accepted). Applies only to hidden
    failure modes of protective devices; the acceptable U (and, for safety
    consequences, the underlying risk acceptance) is a HITL decision.
    """
    _require_positive(mtive=mtive)
    if not 0 < u < 1:
        raise ValueError(f"u must be in the open interval (0, 1), got {u}")
    ffi = 2.0 * u * mtive
    return _build_result(
        "availability", ffi, "FFI = 2 * U * Mtive", {"mtive": mtive, "u": u}, mtive
    )


def ffi_single_single(mtive: float, mted: float, mmf: float) -> FFIResult:
    """Single protected function, single protective device (no redundancy).

    FFI = 2 * Mtive * Mted / Mmf  (no square root).

    Equivalent to the availability formula with the required unavailability
    U_required = Mted / Mmf. Applies only to hidden failure modes; Mmf
    acceptance for safety-consequence multiple failures is a HITL decision.
    """
    _require_positive(mtive=mtive, mted=mted, mmf=mmf)
    ffi = 2.0 * mtive * mted / mmf
    return _build_result(
        "single_single",
        ffi,
        "FFI = 2 * Mtive * Mted / Mmf",
        {"mtive": mtive, "mted": mted, "mmf": mmf},
        mtive,
    )


def ffi_multi_single(mtive: float, mted_list: list[float], mmf: float) -> FFIResult:
    """Multiple protected functions, single protective device.

    FFI = 2 * Mtive / (sum(1 / Mted_i) * Mmf)  (no square root).

    One protective device (e.g. a surge protector) guards several protected
    functions with MTBFs ``mted_list``; demands on the protection add up as
    the sum of failure rates. Applies only to hidden failure modes; Mmf
    acceptance for safety-consequence multiple failures is a HITL decision.
    """
    _require_positive(mtive=mtive, mmf=mmf)
    if not mted_list:
        raise ValueError("mted_list must contain at least one Mted value")
    for i, mted in enumerate(mted_list):
        _require_positive(**{f"mted_list[{i}]": mted})
    demand_rate = sum(1.0 / mted for mted in mted_list)
    ffi = 2.0 * mtive / (demand_rate * mmf)
    return _build_result(
        "multi_single",
        ffi,
        "FFI = 2 * Mtive / (sum(1/Mted_i) * Mmf)",
        {"mtive": mtive, "mted_list": list(mted_list), "mmf": mmf},
        mtive,
    )


def ffi_single_multi(mtive: float, mted: float, mmf: float, n: int) -> FFIResult:
    """Single protected function, n redundant protective devices.

    FFI = Mtive * [ (n + 1) * Mted / Mmf ] ** (1 / n)

    Simplified n-of-n model: all n redundant protective devices must have
    failed for protection to be lost. Reduces exactly to the
    single/single formula (2 * Mtive * Mted / Mmf) at n = 1. Applies only
    to hidden failure modes; Mmf acceptance for safety-consequence
    multiple failures is a HITL decision.
    """
    _require_positive(mtive=mtive, mted=mted, mmf=mmf)
    if not isinstance(n, int) or isinstance(n, bool):
        raise ValueError(f"n must be an integer, got {n!r}")
    if n < 1:
        raise ValueError(f"n must be >= 1, got {n}")
    ffi = mtive * ((n + 1) * mted / mmf) ** (1.0 / n)
    return _build_result(
        "single_multi",
        ffi,
        "FFI = Mtive * [(n+1) * Mted / Mmf]^(1/n)",
        {"mtive": mtive, "mted": mted, "mmf": mmf, "n": n},
        mtive,
    )


def ffi_economic(mtive: float, mted: float, cmf: float, cff: float) -> FFIResult:
    """Economic FFI: FFI = sqrt(2 * Mtive * Mted * Cff / Cmf).

    Balances the cost of performing failure finding (Cff per task) against
    the cost of a multiple failure (Cmf). This is the one method that
    legitimately contains a square root. Use only where the multiple
    failure has purely economic consequences - safety or environmental
    consequences must not be traded off on cost alone (HITL decision).
    """
    _require_positive(mtive=mtive, mted=mted, cmf=cmf, cff=cff)
    ffi = math.sqrt(2.0 * mtive * mted * cff / cmf)
    return _build_result(
        "economic",
        ffi,
        "FFI = sqrt(2 * Mtive * Mted * Cff / Cmf)",
        {"mtive": mtive, "mted": mted, "cmf": cmf, "cff": cff},
        mtive,
    )


_METHODS: dict[str, Callable[..., FFIResult]] = {
    "availability": ffi_availability,
    "single_single": ffi_single_single,
    "multi_single": ffi_multi_single,
    "single_multi": ffi_single_multi,
    "economic": ffi_economic,
}


def calculate_ffi(method: str, params: dict[str, Any]) -> FFIResult:
    """Dispatch an FFI calculation by method name.

    ``method`` is one of: ``availability``, ``single_single``,
    ``multi_single`` (multiple protected functions / single device),
    ``single_multi`` (single function / multiple redundant devices),
    ``economic``. ``params`` holds the keyword arguments of the
    corresponding ``ffi_*`` function.
    """
    try:
        func = _METHODS[method]
    except KeyError:
        known = ", ".join(sorted(_METHODS))
        raise ValueError(f"Unknown FFI method {method!r}; expected one of: {known}") from None
    return func(**params)
