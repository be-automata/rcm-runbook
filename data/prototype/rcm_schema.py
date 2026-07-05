"""
RCM Agent State Schema - LangGraph State Definition
Maps directly to RCM Workbook structure per SAE JA1011/JA1012.

This schema defines the complete state managed by the RCM AI Agent,
including FMEA data, decision logic outcomes, and maintenance tasks.
"""

import operator
from datetime import datetime
from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ==================== ENUMS ====================

class ConsequenceType(str, Enum):
    """Consequence categories per SAE JA1011 Section 5.5"""
    HIDDEN_SAFETY = "hidden_safety"
    HIDDEN_ENVIRONMENTAL = "hidden_environmental"
    HIDDEN_OPERATIONAL = "hidden_operational"
    HIDDEN_NON_OPERATIONAL = "hidden_non_operational"
    EVIDENT_SAFETY = "evident_safety"
    EVIDENT_ENVIRONMENTAL = "evident_environmental"
    EVIDENT_OPERATIONAL = "evident_operational"
    EVIDENT_NON_OPERATIONAL = "evident_non_operational"


class MaintenanceStrategy(str, Enum):
    """Maintenance strategies per SAE JA1011 Section 5.6"""
    ON_CONDITION = "on_condition"           # CBM/predictive
    SCHEDULED_RESTORATION = "scheduled_restoration"  # Time-based overhaul
    SCHEDULED_DISCARD = "scheduled_discard"  # Time-based replacement
    FAILURE_FINDING = "failure_finding"      # For hidden failures
    COMBINATION = "combination"              # Multiple strategies
    REDESIGN = "redesign"                   # One-time change
    RUN_TO_FAILURE = "run_to_failure"       # No scheduled maintenance


class AgingPattern(str, Enum):
    """Nowlan & Heap failure patterns"""
    PATTERN_A = "A"  # Bathtub curve
    PATTERN_B = "B"  # Wear-out only (increasing hazard)
    PATTERN_C = "C"  # Gradual wear-out
    PATTERN_D = "D"  # Low then constant
    PATTERN_E = "E"  # Constant (random)
    PATTERN_F = "F"  # Infant mortality then constant


class CMTechnology(str, Enum):
    """Condition monitoring technologies for API 610 pumps"""
    VIBRATION_OVERALL = "vibration_overall"
    VIBRATION_SPECTRUM = "vibration_spectrum"
    VIBRATION_BPFO_BPFI = "vibration_bearing_freqs"
    ULTRASOUND = "ultrasound"
    OIL_ANALYSIS = "oil_analysis"
    THERMOGRAPHY = "thermography"
    MOTOR_CURRENT = "motor_current_signature"
    PERFORMANCE_MONITORING = "performance_monitoring"
    VISUAL_INSPECTION = "visual_inspection"


# ==================== FMEA MODELS ====================

class Function(BaseModel):
    """Asset function with quantitative performance standard."""
    id: str = Field(..., description="Unique function ID (e.g., F001)")
    description: str = Field(..., description="Function statement: To [verb] [object] to [standard]")
    verb: str = Field(..., description="Action verb (e.g., pump, contain, seal)")
    object: str = Field(..., description="Subject of action (e.g., process fluid)")
    performance_standard: str = Field(..., description="Quantitative limit (e.g., 500 m³/h ±5%)")
    measurement_unit: str | None = None
    lower_limit: float | None = None
    upper_limit: float | None = None
    function_type: Literal["primary", "secondary", "protective"] = "primary"
    iso14224_function_code: str | None = None  # ISO 14224 Table B.1


class FunctionalFailure(BaseModel):
    """State where function fails to meet performance standard."""
    id: str = Field(..., description="Unique FF ID (e.g., FF001.1)")
    function_id: str = Field(..., description="Parent function ID")
    description: str = Field(..., description="Failure state description")
    failure_type: Literal["total", "partial", "degraded", "erratic", "overspeed"] = "total"


class FailureMode(BaseModel):
    """Reasonably likely cause of functional failure."""
    id: str = Field(..., description="Unique FM ID (e.g., FM001.1.1)")
    functional_failure_id: str
    description: str = Field(..., description="Event causing failure")
    component: str = Field(..., description="Failing component (e.g., impeller)")
    iso14224_failure_mode: str | None = None  # ISO 14224 Table B.7
    failure_mechanism: str | None = None
    
    # Weibull parameters (from fleet data or ISO 14224)
    weibull_beta: float | None = None  # Shape parameter
    weibull_eta: float | None = None   # Scale parameter (hours)
    mtbf_hours: float | None = None
    mttf_hours: float | None = None
    
    # Detection
    detectable: bool = True
    detection_method: CMTechnology | None = None
    pf_interval_hours: float | None = None  # P-F interval for CBM


class Effect(BaseModel):
    """Consequences of failure mode."""
    failure_mode_id: str
    local_effect: str = Field(..., description="Direct consequence on component/function")
    higher_effect: str | None = Field(None, description="Effect on subsystem")
    end_effect: str | None = Field(None, description="Effect on system/plant")
    
    evidence_of_failure: str = Field(..., description="How operators detect failure")
    hidden: bool = Field(..., description="True if not evident during normal operation")
    
    safety_impact: bool = False
    environmental_impact: bool = False
    operational_impact: bool = False
    
    downtime_hours: float | None = None
    repair_cost: float | None = None
    consequential_damage_cost: float | None = None
    production_loss_per_hour: float | None = None


class Criticality(BaseModel):
    """Criticality assessment (RPN/SOD)."""
    failure_mode_id: str
    severity: int = Field(..., ge=1, le=10, description="Impact severity 1-10")
    occurrence: int = Field(..., ge=1, le=10, description="Frequency 1-10")
    detectability: int = Field(..., ge=1, le=10, description="Detection difficulty 1-10")
    
    @property
    def rpn(self) -> int:
        return self.severity * self.occurrence * self.detectability
    
    @property
    def sod(self) -> str:
        return f"{self.severity}{self.occurrence}{self.detectability}"


# ==================== DECISION LOGIC MODELS ====================

class DecisionLogicResult(BaseModel):
    """Result of decision logic traversal per SAE JA1011."""
    failure_mode_id: str
    
    # Decision path flags (maps to workbook columns)
    not_credible: bool = False  # Exclude from analysis
    is_hidden: bool = False
    has_safety_consequence: bool = False
    has_environmental_consequence: bool = False
    has_operational_consequence: bool = False
    
    # Strategy evaluation results
    on_condition_applicable: bool = False
    on_condition_effective: bool = False
    scheduled_restoration_applicable: bool = False
    scheduled_restoration_effective: bool = False
    scheduled_discard_applicable: bool = False
    scheduled_discard_effective: bool = False
    failure_finding_applicable: bool = False
    failure_finding_effective: bool = False
    combination_required: bool = False
    redesign_required: bool = False
    run_to_failure_acceptable: bool = False
    
    selected_strategy: MaintenanceStrategy
    consequence_type: ConsequenceType
    
    # Justification (required per JA1011)
    justification: str = Field(..., description="Technical basis for strategy selection")
    aging_pattern: AgingPattern | None = None
    statistical_basis: str | None = None  # e.g., "Weibull β=1.4, 95% CI [1.2, 1.6]"


# ==================== MAINTENANCE TASK MODELS ====================

class MaintenanceTask(BaseModel):
    """Scheduled maintenance task."""
    id: str
    failure_mode_id: str
    strategy: MaintenanceStrategy
    
    task_type: Literal["inspection", "test", "service", "overhaul", "replace"] = "inspection"
    description: str
    procedure_ref: str | None = None
    
    # Interval (one of these populated based on strategy)
    interval_hours: float | None = None
    interval_days: float | None = None
    interval_calendar_months: int | None = None
    
    # For CBM tasks
    condition_indicator: str | None = None  # e.g., "Vibration velocity @ DE bearing"
    alert_threshold: float | None = None
    action_threshold: float | None = None
    pf_interval_hours: float | None = None
    
    # Resources
    craft_skills: list[str] = Field(default_factory=list)
    estimated_duration_hours: float = 1.0
    parts_required: list[str] = Field(default_factory=list)
    tools_required: list[str] = Field(default_factory=list)
    estimated_cost: float | None = None
    
    # SAE JA1011 compliance
    technically_feasible: bool = True
    worth_doing: bool = True
    justification: str = ""


# ==================== AGENT STATE (LangGraph) ====================

class RCMAnalysisState(BaseModel):
    """
    Complete RCM analysis state for LangGraph agent.
    Maps to RCM Workbook structure.
    """
    # Metadata
    analysis_id: str
    analysis_title: str
    system_name: str
    product_name: str | None = None
    asset_tag: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    version: int = 1
    
    # Operating context
    operating_context: dict = Field(
        default_factory=dict,
        description="Environmental conditions, load profile, criticality"
    )
    
    # FMEA data (Questions 1-4)
    functions: list[Function] = Field(default_factory=list)
    functional_failures: list[FunctionalFailure] = Field(default_factory=list)
    failure_modes: list[FailureMode] = Field(default_factory=list)
    effects: list[Effect] = Field(default_factory=list)
    criticalities: list[Criticality] = Field(default_factory=list)
    
    # Decision logic results (Questions 5-7)
    decision_results: list[DecisionLogicResult] = Field(default_factory=list)
    
    # Maintenance tasks (output)
    tasks: list[MaintenanceTask] = Field(default_factory=list)
    
    # Agent workflow state
    current_phase: Literal[
        "initialization",
        "fmea_functions",
        "fmea_failures",
        "fmea_effects",
        "criticality",
        "decision_logic",
        "task_selection",
        "interval_optimization",
        "review",
        "complete"
    ] = "initialization"
    
    pending_hitl_reviews: list[str] = Field(
        default_factory=list,
        description="Failure mode IDs requiring human review"
    )
    
    # Analysis results
    total_failure_modes: int = 0
    hidden_failure_count: int = 0
    safety_critical_count: int = 0
    cbm_task_count: int = 0
    rtf_count: int = 0
    
    # Confidence tracking
    data_quality_score: float = 0.0  # 0-1
    analysis_confidence: float = 0.0  # 0-1


# ==================== LANGGRAPH REDUCER STATE ====================

class AgentState(BaseModel):
    """
    LangGraph agent state with reducers for message accumulation.
    Used for multi-agent coordination (supervisor + sub-agents).
    """
    # Core RCM state
    rcm_analysis: RCMAnalysisState
    
    # Conversation history (append-only via reducer)
    messages: Annotated[list, operator.add] = Field(default_factory=list)
    
    # Agent coordination
    current_agent: Literal[
        "supervisor",
        "rag_agent",
        "analysis_agent",
        "maintenance_agent",
        "research_agent"
    ] = "supervisor"
    
    next_agent: str | None = None
    
    # Tool call results (for RAG/search)
    retrieved_documents: list[dict] = Field(default_factory=list)
    web_search_results: list[dict] = Field(default_factory=list)
    
    # Mode A/B state
    mode: Literal["A_static_build", "B_dynamic_update"] = "A_static_build"
    
    # Trigger tracking for Mode B
    trigger_type: Literal["new_failure_event", "cmms_work_order", "cm_alert", "oem_bulletin", "regulation_change", "cost_change", "scheduled_review"] | None = None
    
    trigger_data: dict | None = None


# ==================== VALIDATION ====================

def validate_ja1011_compliance(state: RCMAnalysisState) -> list[str]:
    """Validate analysis against SAE JA1011 criteria."""
    issues = []
    
    # Check all failure modes have decision results
    fm_ids = {fm.id for fm in state.failure_modes}
    dr_ids = {dr.failure_mode_id for dr in state.decision_results}
    missing = fm_ids - dr_ids
    if missing:
        issues.append(f"Missing decision logic for: {missing}")
    
    # Check safety/environmental FMs have proactive tasks or redesign
    for dr in state.decision_results:
        if dr.has_safety_consequence or dr.has_environmental_consequence:
            if dr.selected_strategy == MaintenanceStrategy.RUN_TO_FAILURE:
                issues.append(
                    f"JA1011 violation: {dr.failure_mode_id} has safety/env consequence "
                    f"but RTF selected"
                )
    
    # Check hidden failures have failure finding or redesign
    for dr in state.decision_results:
        if dr.is_hidden and dr.selected_strategy not in [
            MaintenanceStrategy.FAILURE_FINDING,
            MaintenanceStrategy.COMBINATION,
            MaintenanceStrategy.REDESIGN
        ]:
            issues.append(
                f"JA1011 warning: {dr.failure_mode_id} is hidden but no FF task"
            )
    
    # Check all tasks have justification
    for task in state.tasks:
        if not task.justification:
            issues.append(f"Task {task.id} missing justification")
    
    return issues


if __name__ == "__main__":
    # Example: Initialize state for API 610 OH2 pump
    state = RCMAnalysisState(
        analysis_id="RCM-2024-001",
        analysis_title="API 610 OH2 Centrifugal Pump RCM Analysis",
        system_name="Process Water Cooling System",
        product_name="API 610 OH2 Pump (Frame 4×6×10)",
        operating_context={
            "fluid": "Process water with 50ppm solids",
            "temperature_c": 85,
            "flow_rate_m3h": 250,
            "discharge_pressure_bar": 12,
            "operating_hours_per_year": 8000,
            "redundancy": "N+1",
            "criticality": "Production critical"
        }
    )
    
    # Add a function
    state.functions.append(Function(
        id="F001",
        description="To pump process water at 250 m³/h ± 5% at 12 bar discharge",
        verb="pump",
        object="process water",
        performance_standard="250 m³/h ± 5% at 12 bar discharge",
        measurement_unit="m³/h",
        lower_limit=237.5,
        upper_limit=262.5,
        function_type="primary"
    ))
    
    print(f"State initialized: {state.analysis_id}")
    print(f"Functions: {len(state.functions)}")
    print(f"Phase: {state.current_phase}")
