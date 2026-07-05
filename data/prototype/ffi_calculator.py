"""
Failure Finding Interval Calculator
Based on RCM Handbook formulas (SAE JA1011 compliant)
Implements all 4 FFI calculation methods.
"""
import math
from dataclasses import dataclass
from enum import Enum
from typing import Any


class FFIMethod(Enum):
    AVAILABILITY = "availability"
    SINGLE_SINGLE = "single_single"  
    MULTI_SINGLE = "multi_single"
    SINGLE_MULTI = "single_multi"
    ECONOMIC = "economic"

@dataclass
class FFIResult:
    method: FFIMethod
    interval_hours: float
    interval_days: float
    interval_months: float
    formula_used: str
    inputs_used: dict[str, Any]
    warnings: list[str]
    is_valid: bool

def calculate_ffi_availability(mtive: float, u: float) -> FFIResult:
    """Availability-based: FFI = 2 × U × Mtive"""
    warnings = []
    if u <= 0 or u >= 1:
        warnings.append(f"Unavailability U={u} should be between 0 and 1")
    if mtive <= 0:
        warnings.append("Mtive must be positive")
        return FFIResult(FFIMethod.AVAILABILITY, 0, 0, 0, "2 × U × Mtive", 
                        {"mtive": mtive, "u": u}, warnings, False)
    ffi_hours = 2 * u * mtive
    return FFIResult(FFIMethod.AVAILABILITY, ffi_hours, ffi_hours/24, ffi_hours/720,
                    "FFI = 2 × U × Mtive", {"mtive": mtive, "u": u}, warnings, len(warnings)==0)

def calculate_ffi_single_single(mtive: float, mted: float, mmf: float) -> FFIResult:
    """Single protective / single protected: FFI = sqrt(2 × Mtive × Mted / Mmf)"""
    warnings = []
    for name, val in [("mtive", mtive), ("mted", mted), ("mmf", mmf)]:
        if val <= 0:
            warnings.append(f"{name} must be positive")
    if warnings:
        return FFIResult(FFIMethod.SINGLE_SINGLE, 0, 0, 0, "sqrt(2 × Mtive × Mted / Mmf)",
                        {"mtive": mtive, "mted": mted, "mmf": mmf}, warnings, False)
    ffi_hours = math.sqrt((2 * mtive * mted) / mmf)
    return FFIResult(FFIMethod.SINGLE_SINGLE, ffi_hours, ffi_hours/24, ffi_hours/720,
                    "FFI = sqrt(2 × Mtive × Mted / Mmf)", 
                    {"mtive": mtive, "mted": mted, "mmf": mmf}, warnings, True)

def calculate_ffi_multi_single(mtive: float, mted_list: list[float], mmf_list: list[float]) -> FFIResult:
    """Multiple functions / single protective: FFI = sqrt(2 × Mtive / Σ(1/(Mted × Mmf)))"""
    warnings = []
    if mtive <= 0:
        warnings.append("Mtive must be positive")
    if len(mted_list) != len(mmf_list):
        warnings.append("Mted and Mmf lists must have same length")
    if warnings:
        return FFIResult(FFIMethod.MULTI_SINGLE, 0, 0, 0, "sqrt(2 × Mtive / Σ(1/(Mted × Mmf)))",
                        {"mtive": mtive, "mted_list": mted_list, "mmf_list": mmf_list}, warnings, False)
    denom = sum(1 / (mted * mmf) for mted, mmf in zip(mted_list, mmf_list))
    ffi_hours = math.sqrt((2 * mtive) / denom)
    return FFIResult(FFIMethod.MULTI_SINGLE, ffi_hours, ffi_hours/24, ffi_hours/720,
                    "FFI = sqrt(2 × Mtive / Σ(1/(Mted × Mmf)))",
                    {"mtive": mtive, "mted_list": mted_list, "mmf_list": mmf_list}, warnings, True)

def calculate_ffi_single_multi(mtive: float, mted: float, mmf: float, n: int) -> FFIResult:
    """Single function / multiple redundant protective: FFI = Mtive × ((n+1) × Mted / Mmf)^(1/n)"""
    warnings = []
    for name, val in [("mtive", mtive), ("mted", mted), ("mmf", mmf)]:
        if val <= 0:
            warnings.append(f"{name} must be positive")
    if n < 1:
        warnings.append("n must be >= 1")
    if warnings:
        return FFIResult(FFIMethod.SINGLE_MULTI, 0, 0, 0, "Mtive × ((n+1) × Mted / Mmf)^(1/n)",
                        {"mtive": mtive, "mted": mted, "mmf": mmf, "n": n}, warnings, False)
    base = ((n + 1) * mted) / mmf
    ffi_hours = mtive * (base ** (1 / n))
    return FFIResult(FFIMethod.SINGLE_MULTI, ffi_hours, ffi_hours/24, ffi_hours/720,
                    "FFI = Mtive × ((n+1) × Mted / Mmf)^(1/n)",
                    {"mtive": mtive, "mted": mted, "mmf": mmf, "n": n}, warnings, True)

def calculate_ffi_economic(mtive: float, mted: float, cmf: float, cff: float) -> FFIResult:
    """Economic-based: FFI = sqrt(2 × Mtive × Mted × Cff / Cmf)"""
    warnings = []
    for name, val in [("mtive", mtive), ("mted", mted), ("cmf", cmf), ("cff", cff)]:
        if val <= 0:
            warnings.append(f"{name} must be positive")
    if warnings:
        return FFIResult(FFIMethod.ECONOMIC, 0, 0, 0, "sqrt(2 × Mtive × Mted × Cff / Cmf)",
                        {"mtive": mtive, "mted": mted, "cmf": cmf, "cff": cff}, warnings, False)
    ffi_hours = math.sqrt((2 * mtive * mted * cff) / cmf)
    return FFIResult(FFIMethod.ECONOMIC, ffi_hours, ffi_hours/24, ffi_hours/720,
                    "FFI = sqrt(2 × Mtive × Mted × Cff / Cmf)",
                    {"mtive": mtive, "mted": mted, "cmf": cmf, "cff": cff}, warnings, True)

def calculate_ffi(
    mtive: float,
    mted: float | None = None,
    mmf: float | None = None,
    u: float | None = None,
    n: int = 1,
    cmf: float | None = None,
    cff: float | None = None,
    mted_list: list[float] | None = None,
    mmf_list: list[float] | None = None,
    method: FFIMethod | None = None
) -> FFIResult:
    """Main FFI dispatcher - auto-selects method based on provided parameters."""
    if method is None:
        if mted_list is not None and mmf_list is not None:
            method = FFIMethod.MULTI_SINGLE
        elif cmf is not None and cff is not None:
            method = FFIMethod.ECONOMIC
        elif n > 1 and mted is not None and mmf is not None:
            method = FFIMethod.SINGLE_MULTI
        elif mted is not None and mmf is not None:
            method = FFIMethod.SINGLE_SINGLE
        elif u is not None:
            method = FFIMethod.AVAILABILITY
        else:
            raise ValueError("Insufficient parameters to determine FFI method")
    
    dispatch = {
        FFIMethod.AVAILABILITY: lambda: calculate_ffi_availability(mtive, u),
        FFIMethod.SINGLE_SINGLE: lambda: calculate_ffi_single_single(mtive, mted, mmf),
        FFIMethod.MULTI_SINGLE: lambda: calculate_ffi_multi_single(mtive, mted_list, mmf_list),
        FFIMethod.SINGLE_MULTI: lambda: calculate_ffi_single_multi(mtive, mted, mmf, n),
        FFIMethod.ECONOMIC: lambda: calculate_ffi_economic(mtive, mted, cmf, cff),
    }
    return dispatch[method]()

def ffi_tool(params: dict) -> dict:
    """LangGraph tool wrapper for FFI calculation."""
    try:
        result = calculate_ffi(**params)
        return {
            "success": True,
            "method": result.method.value,
            "interval_hours": round(result.interval_hours, 2),
            "interval_days": round(result.interval_days, 2),
            "interval_months": round(result.interval_months, 2),
            "formula": result.formula_used,
            "inputs": result.inputs_used,
            "warnings": result.warnings,
            "is_valid": result.is_valid
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

if __name__ == "__main__":
    print("=== FFI Calculator Tests (API 610 OH2 Pump) ===\n")
    r1 = calculate_ffi_availability(mtive=43800, u=0.02)
    print(f"Vibration Alarm (availability): {r1.interval_months:.1f} months")
    r2 = calculate_ffi_single_single(mtive=35040, mted=8760, mmf=876000)
    print(f"Low Pressure Switch: {r2.interval_months:.1f} months")
    r3 = calculate_ffi_single_multi(mtive=17520, mted=25000, mmf=500000, n=2)
    print(f"Redundant Seal Detection: {r3.interval_months:.1f} months")
    r4 = calculate_ffi_economic(mtive=43800, mted=8760, cmf=150000, cff=500)
    print(f"Economic Optimal: {r4.interval_months:.1f} months")
