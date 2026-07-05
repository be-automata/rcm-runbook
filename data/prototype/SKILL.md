---
name: rcm-analysis
description: |
  Dynamic RCM AI Agent for API 610 OH2 centrifugal pumps. Performs SAE JA1011/JA1012 
  compliant Reliability-Centered Maintenance analysis with Mode A (static build) and 
  Mode B (dynamic update) capabilities.
triggers:
  - "RCM analysis"
  - "failure mode analysis"
  - "maintenance strategy"
  - "FMEA"
  - "failure finding interval"
  - "P-F interval"
  - "Weibull"
  - "centrifugal pump maintenance"
  - "API 610"
---

# RCM Analysis Agent Skill

## Capabilities

### Mode A: Static RCM Build
Construct complete RCM analysis from asset data:
1. **Operating Context**: Environmental conditions, criticality, redundancy
2. **FMEA Generation**: Functions → Functional Failures → Failure Modes → Effects
3. **Criticality Assessment**: Severity × Occurrence × Detectability = RPN
4. **Decision Logic**: SAE JA1011 tree traversal (Hidden? → Consequence? → Strategy?)
5. **Task Selection**: CBM > Restoration > Discard > FF > RTF
6. **Interval Calculation**: Weibull-based, FFI formulas, P-F analysis

### Mode B: Dynamic Update
Continuous improvement via trigger-based updates:
- **Triggers**: New failure, CM alert, OEM bulletin, regulation, cost variance, review
- **Evaluation**: Laplace trend test, Weibull parameter refit, CI comparison
- **Decision**: Change required if β shift >10% or p<0.05
- **HITL Gate**: Mandatory for safety/environmental consequences

## Tools Available

### calculate_ffi(mtive, mted, mmf, u, n_redundant, cmf, cff)
Calculate Failure Finding Interval using 4 methods:
- Availability-based: `2 × U × Mtive`
- Single-single: `√(2 × Mtive × Mted / Mmf)`
- Single-multi (voting): `Mtive × [(n+1) × Mted / Mmf]^(1/n)`
- Economic: `√(2 × Mtive × Mted × Cff / Cmf)`

### weibull_fit(failure_times, censoring)
Fit Weibull distribution to failure data:
- Maximum Likelihood Estimation
- Returns β (shape), η (scale), 95% CI
- Supports right-censored data

### laplace_test(failure_times)
Test for reliability trend:
- H0: Homogeneous Poisson Process (constant failure rate)
- Returns U-statistic, p-value, interpretation
- |U| > 1.96 indicates significant trend

### pf_interval_estimate(condition_data, failure_events)
Estimate P-F interval from CM data:
- Correlates condition indicator degradation to failure
- Returns interval in hours with confidence bounds

## Constraints (SAE JA1011 Compliance)

### MUST
- Analyze operating context before FMEA
- Consider all 6 failure patterns (Nowlan & Heap)
- Evaluate strategies in priority order
- Document justification for every task
- Flag safety/environmental for HITL

### MUST NOT
- Select RTF for safety/environmental consequences
- Change intervals without statistical justification
- Bypass HITL for critical decisions
- Use unvalidated Weibull parameters

### Statistical Rigor
- Minimum 5 failures for Weibull fit
- 95% CI must not span ±50% of point estimate
- Laplace test before trend conclusions
- Document data source and quality score

## ISO 14224 Alignment

### Equipment Taxonomy
```
2.3 Rotating Equipment → Centrifugal Pump
  └─ 2.3.1 Impeller
  └─ 2.3.2 Shaft
  └─ 2.3.3 Bearings (DE, NDE, Thrust)
  └─ 2.3.4 Seals (Mechanical, Stuffing box)
  └─ 2.3.5 Coupling
  └─ 2.3.6 Casing
  └─ 2.3.7 Wear rings
```

### Failure Mode Codes
Reference ISO 14224 Table B.7 for standardized failure modes.

## Example Invocations

### Mode A: New Analysis
```
User: Perform RCM analysis for pump P-1001 (API 610 OH2, cooling water service)
Agent: 
1. Load operating context from CMMS/asset register
2. Retrieve ISO 14224 functions for centrifugal pumps
3. Generate FMEA with fleet Weibull parameters
4. Traverse decision logic for each FM
5. Calculate intervals (CBM: P-F/2, Discard: 0.9×η)
6. Flag safety FMs for HITL review
7. Export RCM workbook
```

### Mode B: Update Trigger
```
Trigger: New failure event - Seal leak on PMP-OH2-003
Agent:
1. Log failure to history (component, mode, TTF)
2. Refit Weibull with new data point
3. Compare β_new vs β_prior
4. Laplace test on recent failure times
5. If significant change: propose interval adjustment
6. Route to HITL if consequence is safety/env
7. Update MEMORY.md with decision
```

## Integration Points

### Data Sources
- **CMMS**: SAP PM (PM01/PM03 work orders)
- **CM System**: Vibration, oil analysis, thermography
- **Asset Register**: Equipment hierarchy, criticality
- **OEM**: Service bulletins, manuals (RAG indexed)
- **Standards**: JA1011, JA1012, ISO 14224, API 610/682

### Outputs
- RCM Workbook (Excel)
- Task list (JSON for CMMS integration)
- Decision audit trail (Markdown)
- Statistical reports (PDF)
