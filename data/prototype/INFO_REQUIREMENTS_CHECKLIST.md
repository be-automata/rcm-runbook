# RCM Information Requirements Checklist

## Dynamic RCM Agent for API 610 OH2 Centrifugal Pumps

This checklist defines all information required to perform SAE JA1011/JA1012 compliant RCM analysis. Sections A–I correspond to standard RCM information requirements per IEC 60300-3-11.

---

## Section A: Asset Register & Hierarchy

### A.1 Equipment Identification
| Field | Required | Source | Example |
|-------|----------|--------|---------|
| Equipment Tag | ✓ | CMMS | PMP-OH2-001 |
| Equipment Description | ✓ | CMMS | Cooling Water Pump |
| Equipment Class | ✓ | CMMS | Centrifugal Pump |
| API Type | ✓ | Engineering | OH2 (Overhung, Two Bearings) |
| Manufacturer | ✓ | Nameplate | Flowserve |
| Model Number | ✓ | Nameplate | 3LD6 |
| Serial Number | ✓ | Nameplate | 2024-CW-0001 |
| Installation Date | ✓ | CMMS | 2020-01-15 |
| Criticality Class | ✓ | Risk Assessment | A/B/C |
| Redundancy | ✓ | P&ID | N+1, 2oo3, etc. |

### A.2 Location Hierarchy
| Level | Field | Example |
|-------|-------|---------|
| 1 | Site | Refinery Alpha |
| 2 | Area | Process Area 3 |
| 3 | Unit | Cooling Water System |
| 4 | System | CW Distribution |
| 5 | Equipment | PMP-OH2-001 |
| 6 | Component | Mechanical Seal |

### A.3 ISO 14224 Taxonomy Mapping
| ISO Level | API 610 OH2 Mapping |
|-----------|---------------------|
| Level 5 (System) | Cooling Water / Process / Utility |
| Level 6 (Equipment) | Centrifugal Pump, Overhung |
| Level 7 (Subunit) | Rotating Assembly, Stationary Assembly, Drive End |
| Level 8 (Component) | Impeller, Shaft, Bearing DE, Bearing NDE, Seal, Coupling |

### A.4 Nameplate Data Capture
- [ ] Design flow rate (m³/h)
- [ ] Design head (m)
- [ ] Design pressure (bar)
- [ ] Design temperature (°C)
- [ ] Rated speed (RPM)
- [ ] Motor power (kW)
- [ ] NPSH required (m)
- [ ] Impeller diameter (mm)
- [ ] Material of construction (casing, impeller, shaft)
- [ ] Seal type (API Plan)
- [ ] Bearing type (DE, NDE)
- [ ] Coupling type

---

## Section B: Operating Context

### B.1 Process Parameters
| Parameter | Units | Design | Normal Operating | Alarm | Trip |
|-----------|-------|--------|------------------|-------|------|
| Flow rate | m³/h | | | | |
| Discharge pressure | bar | | | | |
| Suction pressure | bar | | | | |
| Differential pressure | bar | | | | |
| Temperature | °C | | | | |
| Current | A | | | | |
| Vibration (overall) | mm/s | | | | |

### B.2 Operating Profile
| Aspect | Value | Notes |
|--------|-------|-------|
| Operating hours per year | hrs | Continuous / Intermittent |
| Starts per year | count | < 100 / 100-1000 / > 1000 |
| Load profile | % | Constant / Variable |
| Speed variation | % | Fixed / VFD |
| Duty cycle | | Continuous / Standby / Swing |

### B.3 Environmental Conditions
| Factor | Value | ISO 14224 Code |
|--------|-------|----------------|
| Indoor/Outdoor | | I / O |
| Climate zone | | Arctic / Temperate / Tropical |
| Corrosive atmosphere | Y/N | |
| Dusty environment | Y/N | |
| Humidity | % | |
| Ambient temperature range | °C | |

### B.4 Process Fluid Properties
| Property | Value | Units |
|----------|-------|-------|
| Fluid type | | (Water, Hydrocarbon, Acid, etc.) |
| Specific gravity | | |
| Viscosity | cSt | |
| Temperature | °C | |
| Solids content | % | |
| Abrasiveness | | (Low / Medium / High) |
| Corrosiveness | | (Low / Medium / High) |
| H₂S content | ppm | |
| pH | | |

### B.5 Redundancy Configuration
| Configuration | Description |
|---------------|-------------|
| Standalone | No backup, single point of failure |
| N+1 | One spare pump, auto-start |
| 2×100% | Full redundancy, manual switchover |
| 3×50% | Parallel operation, any 2 run |
| 2oo3 voting | Protective device configuration |

---

## Section C: Functions & Performance Standards

### C.1 Primary Functions
| ID | Function Statement | Performance Standard |
|----|-------------------|---------------------|
| F1 | Transfer cooling water from sump to heat exchangers | ≥ 500 m³/h @ ≥ 35 m head |
| F2 | Maintain discharge pressure at header | 4.0 ± 0.5 bar |
| F3 | Contain process fluid | Zero external leakage |
| F4 | Operate within vibration limits | ≤ 4.5 mm/s overall (ISO 10816-3) |

### C.2 Secondary Functions
| ID | Function Statement | Performance Standard |
|----|-------------------|---------------------|
| F5 | Indicate seal health | Seal flush flow 10-15 L/min |
| F6 | Provide bearing lubrication | Oil level visible in sight glass |
| F7 | Maintain alignment | Coupling alignment ≤ 0.05 mm |
| F8 | Signal abnormal conditions | Alarm on high vibration > 7.1 mm/s |

### C.3 Protective Functions (Hidden)
| ID | Function Statement | Performance Standard |
|----|-------------------|---------------------|
| F9 | Protect pump from dry running | Low flow trip at 20% BEP |
| F10 | Protect motor from overload | Thermal overload relay trips at 115% FLA |
| F11 | Detect seal failure | Seal leak detector activates on 50 mL/min |
| F12 | Protect from high temperature | RTD trips at 95°C bearing temp |

### C.4 Performance Standard Sources
- [ ] OEM data sheets and manuals
- [ ] API 610 13th edition specifications
- [ ] ISO 10816-3 vibration severity chart
- [ ] Process engineering specifications
- [ ] P&ID and cause-and-effect diagrams

---

## Section D: Functional Failures

### D.1 Functional Failure Matrix
| Function ID | FF ID | Functional Failure Description |
|-------------|-------|-------------------------------|
| F1 | FF1.1 | Unable to transfer any fluid |
| F1 | FF1.2 | Unable to achieve required flow rate |
| F1 | FF1.3 | Unable to achieve required head |
| F2 | FF2.1 | Discharge pressure too low |
| F2 | FF2.2 | Discharge pressure too high |
| F3 | FF3.1 | External leakage exceeds acceptable limit |
| F4 | FF4.1 | Vibration exceeds alarm limit |
| F4 | FF4.2 | Vibration exceeds trip limit |

### D.2 Functional Failure Evidence
| FF ID | Evidence Type | Detection Method |
|-------|---------------|------------------|
| FF1.1 | Obvious | Zero flow indication, no discharge pressure |
| FF1.2 | Measurable | Flow transmitter below setpoint |
| FF1.3 | Measurable | Discharge pressure below setpoint |
| FF3.1 | Observable | Visual leak at seal, drip detected |
| FF4.1 | Hidden until inspection | Vibration monitor in failed state |

---

## Section E: Failure Modes & Effects Analysis

### E.1 Failure Mode Identification
| FF ID | FM ID | Failure Mode | ISO 14224 Code |
|-------|-------|--------------|----------------|
| FF1.1 | FM1.1.1 | Impeller completely worn | FTS (Fail to start) |
| FF1.1 | FM1.1.2 | Shaft seizure due to bearing failure | STD (Structural deficiency) |
| FF1.1 | FM1.1.3 | Coupling failure | BRD (Breakdown) |
| FF1.2 | FM1.2.1 | Impeller erosion | PLU (Plugged) |
| FF1.2 | FM1.2.2 | Wear ring clearance excessive | INL (Internal leakage) |
| FF3.1 | FM3.1.1 | Mechanical seal face damage | EXL (External leakage) |
| FF3.1 | FM3.1.2 | O-ring degradation | EXL |
| FF4.1 | FM4.1.1 | Bearing defect (BPFO/BPFI) | VIB (Vibration) |
| FF4.1 | FM4.1.2 | Unbalance | VIB |
| FF4.1 | FM4.1.3 | Misalignment | VIB |
| FF4.1 | FM4.1.4 | Cavitation | NOI (Noise) |

### E.2 Effect Capture Template
For each failure mode, capture:
- [ ] Local effect (on component)
- [ ] System effect (on pump function)
- [ ] End effect (on plant operations)
- [ ] Safety/environmental impact
- [ ] Detection method during normal operation
- [ ] Time to effect (immediate / gradual)

### E.3 Weibull Parameters per Component
| Component | Failure Mode | β (Shape) | η (Scale, hrs) | Data Source |
|-----------|--------------|-----------|----------------|-------------|
| Mechanical Seal | Face wear | 1.4 | 25,000 | Fleet history |
| Bearing DE | Fatigue | 1.3 | 40,000 | Fleet history |
| Bearing NDE | Fatigue | 1.3 | 45,000 | Fleet history |
| Impeller | Erosion | 2.5 | 150,000 | OREDA |
| Coupling | Elastomer degradation | 2.0 | 75,000 | OEM bulletin |
| Wear Ring | Clearance increase | 1.8 | 60,000 | Fleet history |

---

## Section F: Consequence Classification

### F.1 Consequence Categories (per SAE JA1011)
| Category | Definition | RCM Implication |
|----------|------------|-----------------|
| Hidden | Failure not evident to operating crew | Must have scheduled task or redesign |
| Safety | Potential for injury or loss of life | Proactive task REQUIRED, no RTF |
| Environmental | Potential for environmental regulation breach | Proactive task REQUIRED, no RTF |
| Operational | Direct economic impact on operations | Cost-justify proactive task |
| Non-operational | No direct operational impact | Cost-justify proactive task |

### F.2 Consequence Assessment Matrix
| FM ID | Hidden? | Safety? | Environmental? | Operational? | Consequence Type |
|-------|---------|---------|----------------|--------------|------------------|
| FM1.1.1 | N | N | N | Y | Operational |
| FM1.1.2 | N | Y | N | Y | Safety |
| FM3.1.1 | N | N | Y | Y | Environmental |
| FM4.1.1 | Y | N | N | N | Hidden |

### F.3 Safety Severity Classification
| Class | Description | Example |
|-------|-------------|---------|
| S1 | Negligible | Minor first aid |
| S2 | Marginal | Medical treatment |
| S3 | Critical | Single fatality or severe injury |
| S4 | Catastrophic | Multiple fatalities |

### F.4 Environmental Impact Classification
| Class | Description | Example |
|-------|-------------|---------|
| E1 | Negligible | No release, contained |
| E2 | Marginal | Minor spill, on-site cleanup |
| E3 | Critical | Reportable release, off-site impact |
| E4 | Catastrophic | Major contamination, prosecution |

---

## Section G: Maintenance Strategy Selection

### G.1 Strategy Priority Order (per SAE JA1011)
1. **On-Condition Task (CBM)**: Detect potential failure before functional failure
2. **Scheduled Restoration**: Restore to original capability at fixed intervals
3. **Scheduled Discard**: Replace at fixed intervals
4. **Failure Finding**: Detect hidden failures at fixed intervals
5. **Combination**: Multiple tasks for complex failure modes
6. **Redesign**: Modify to eliminate failure mode
7. **Run-to-Failure**: Accept failure consequences

### G.2 Strategy Applicability Criteria
| Strategy | Applicable If |
|----------|---------------|
| On-Condition | P-F interval > inspection interval + corrective action lead time |
| Scheduled Restoration | Identifiable wear-out age (β > 1.0); restoration restores capability |
| Scheduled Discard | Identifiable wear-out age (β > 1.0); item not restorable |
| Failure Finding | Hidden failure; test reveals functional status |
| Combination | Single task insufficient to address all consequence types |
| Redesign | No applicable task; consequence unacceptable |
| Run-to-Failure | Non-hidden; consequence acceptable; no proactive task cost-effective |

### G.3 P-F Intervals by Condition Technology
| Technology | Detectable Faults | Typical P-F | Inspection Interval |
|------------|-------------------|-------------|---------------------|
| Vibration (overall) | Imbalance, misalignment | 1-3 months | Weekly |
| Vibration (spectral) | Bearing defects (BPFO/BPFI) | 2-6 weeks | Weekly |
| Oil analysis (wear metals) | Bearing wear, gear wear | 2-4 months | Monthly |
| Oil analysis (particle count) | Contamination | 1-2 months | Monthly |
| Thermography | Bearing hot spots, electrical | 1-2 months | Monthly |
| Ultrasound | Lubrication, bearing defects | 1-3 months | Monthly |
| Performance monitoring | Degradation, efficiency loss | 3-6 months | Continuous |
| Motor current (MCSA) | Rotor bar, eccentricity | 2-4 months | Monthly |

### G.4 Strategy Selection per Failure Mode
| FM ID | Strategy | Task Type | Justification |
|-------|----------|-----------|---------------|
| FM3.1.1 | CBM | Seal flush flow monitoring | P-F 4-6 weeks, continuous monitoring |
| FM4.1.1 | CBM | Vibration spectral analysis | P-F 2-6 weeks, weekly trending |
| FM1.2.2 | Scheduled Discard | Wear ring replacement | β=1.8, predictable wear-out |
| FM1.1.3 | CBM + Discard | Alignment check + elastomer replace | Combination task |

---

## Section H: Task Interval Calculation

### H.1 On-Condition Task Interval
**Rule**: Inspection interval ≤ P-F interval / 2 (allows one missed inspection)

| FM ID | P-F Interval | Inspection Interval | Technology |
|-------|--------------|---------------------|------------|
| FM4.1.1 | 4 weeks | 2 weeks | Vibration spectral |
| FM3.1.1 | 6 weeks | 3 weeks | Seal flush flow |
| FM4.1.2 | 8 weeks | 4 weeks | Vibration overall |

### H.2 Scheduled Restoration/Discard Interval
**Rule**: Interval = η × safe-life factor (typically 0.9η for β > 1.5)

| FM ID | β | η (hrs) | Interval | Task |
|-------|---|---------|----------|------|
| FM1.2.2 | 1.8 | 60,000 | 54,000 hrs | Wear ring replacement |
| FM1.1.3 | 2.0 | 75,000 | 67,500 hrs | Coupling elastomer replacement |

### H.3 Failure Finding Interval (FFI)

**Input Requirements**:
| Symbol | Description | Required For |
|--------|-------------|--------------|
| Mtive | MTBF of protective device | All methods |
| Mted | MTBF of protected function | Single-single, multi-single, economic |
| Mmf | Acceptable MTBF for multiple failure | Single-single, multi-single |
| U | Acceptable unavailability (decimal) | Availability-based |
| n | Number of redundant protective devices | Multi-single |
| Cmf | Cost of multiple failure | Economic |
| Cff | Cost of failure finding task | Economic |

**Formulas**:

| Method | Formula | When to Use |
|--------|---------|-------------|
| Availability | FFI = 2 × U × Mtive | Simple availability target |
| Single-Single | FFI = √(2 × Mtive × Mted / Mmf) | One device, one protected function |
| Single-Multi | FFI = √(2 × Mtive × Σ(1/Mted) × Mmf) | One device, multiple protected functions |
| Multi-Single | FFI = Mtive × [(n+1) × Mted / Mmf]^(1/n) | Redundant protective devices |
| Economic | FFI = √(2 × Mtive × Mted × Cff / Cmf) | Cost optimization |

### H.4 FFI Calculation Example
| Parameter | Value |
|-----------|-------|
| Protective device | Low flow trip |
| Mtive | 50,000 hrs |
| Mted (dry running damage) | 100,000 hrs |
| Mmf (acceptable) | 1,000,000 hrs |
| **FFI (Single-Single)** | **3,162 hrs (~4 months)** |

### H.5 Interval Adjustment Criteria
Interval changes require statistical justification:
- [ ] Weibull β shift > 10% with non-overlapping 95% CI
- [ ] Laplace test p-value < 0.05 (significant trend)
- [ ] Minimum 5 failure data points for Weibull refit
- [ ] HITL approval for S/E consequence failure modes

---

## Section I: Task Packaging & Implementation

### I.1 Task List Template
| Task ID | FM ID | Task Description | Strategy | Interval | Duration | Craft | Running? |
|---------|-------|------------------|----------|----------|----------|-------|----------|
| T001 | FM4.1.1 | Collect vibration spectral data | CBM | 2 weeks | 30 min | Tech | Yes |
| T002 | FM3.1.1 | Check seal flush flow rate | CBM | 1 week | 10 min | Op | Yes |
| T003 | FM1.2.2 | Replace wear rings | Discard | 54,000 hrs | 8 hrs | Mech | No |
| T004 | Hidden | Test low flow trip | FF | 3,162 hrs | 1 hr | I&E | No |

### I.2 Task Packaging Rules
| Principle | Description |
|-----------|-------------|
| Opportunity maintenance | Group tasks when equipment down for major task |
| Interval harmonization | Round intervals to operational calendar (weekly/monthly/annually) |
| Craft grouping | Combine tasks requiring same craft skills |
| Running/Stopped | Separate running tasks from shutdown tasks |
| Outage alignment | Align major tasks with planned turnarounds |

### I.3 Resource Requirements
| Task Type | Typical Resources |
|-----------|-------------------|
| Vibration data collection | Portable analyzer, trained technician |
| Oil sampling | Sample bottles, pump isolation procedure |
| Alignment check | Laser alignment tool, 2 mechanics |
| Seal replacement | Seal kit, lifting equipment, 2 mechanics |
| Bearing replacement | Bearing puller, induction heater, 2 mechanics |

### I.4 Spares Inventory Requirements
| Component | Reorder Point | Lead Time | Min Stock | Criticality |
|-----------|---------------|-----------|-----------|-------------|
| Mechanical seal | 1 | 4 weeks | 2 | High |
| Bearing set (DE + NDE) | 1 | 2 weeks | 2 | High |
| Coupling elastomer | 1 | 2 weeks | 1 | Medium |
| Wear ring set | 1 | 6 weeks | 1 | Medium |
| O-ring kit | 2 | 1 week | 4 | Low |

### I.5 Work Order Integration (SAP PM Schema)
| Field | Mapping |
|-------|---------|
| Order Type | PM01 (Corrective) / PM03 (Preventive) |
| Functional Location | Equipment tag |
| Maintenance Plan | RCM-derived task list |
| Task List | Linked to FM ID |
| Notification Type | M1 (Malfunction) for failures |
| Damage Code | ISO 14224 failure mode code |

### I.6 CMMS Data Collection Requirements
For Mode B dynamic updates, collect:
- [ ] Failure date/time (notification creation)
- [ ] Time to failure (last PM to failure)
- [ ] Failure mode (ISO 14224 code)
- [ ] Failure cause (root cause category)
- [ ] Effect on function (partial/complete)
- [ ] Detection method (routine/CM/operator)
- [ ] Repair duration
- [ ] Repair cost (labor + materials)
- [ ] Parts replaced

### I.7 Documentation Requirements
| Document | Purpose | Retention |
|----------|---------|-----------|
| RCM Workbook | Full analysis record | Life of asset |
| Decision audit trail | Justification for each task | Life of asset |
| Interval change log | Statistical justification | 10 years |
| HITL approval records | Safety/environmental sign-off | 10 years |
| FMEA revision history | Track analysis evolution | Life of asset |

### I.8 Review Schedule
| Review Type | Frequency | Trigger |
|-------------|-----------|---------|
| Routine review | 12-24 months | Calendar |
| Post-failure review | Within 30 days | Significant failure |
| Regulation change | As needed | New regulation |
| Technology change | As needed | New CM capability |
| Cost variance | Quarterly | Budget deviation > 15% |

---

## Checklist Completion Status

| Section | Status | Owner | Date |
|---------|--------|-------|------|
| A: Asset Register | ☐ | | |
| B: Operating Context | ☐ | | |
| C: Functions | ☐ | | |
| D: Functional Failures | ☐ | | |
| E: FMEA | ☐ | | |
| F: Consequences | ☐ | | |
| G: Strategy Selection | ☐ | | |
| H: Intervals | ☐ | | |
| I: Implementation | ☐ | | |

---

*Document Version: 1.0*  
*Standard Reference: SAE JA1011, SAE JA1012, IEC 60300-3-11, ISO 14224*  
*Last Updated: 2026-04-11*
