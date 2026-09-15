"""
schemas.py — Pydantic v2 models for RecruitAI.

Two primary schemas:
  • CandidateExtractedData — output of the Reader node (Gemini structured output).
    This is the structured "extract" of a candidate's resume that the
    deterministic Evaluator consumes. The LLM never makes eligibility
    decisions; it only fills this schema.
  • EvaluationResult       — output of the Evaluator node (pure Python logic).
    Contains the Tier 1 eligibility decision and the Tier 2 comparative score.

Design notes:
  - Field names mirror the rubric keys in config/aicte_rubric.json so the
    evaluator can look up criteria dynamically without brittle string mapping.
  - All boolean flags default to False and counts to 0 so a partially parsed
    resume degrades gracefully (fails criteria) rather than passing by accident.
  - `assume_role` lets the Reader node capture the role parsed from the email
    subject, while `applied_role` is the canonical role used downstream.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field, ConfigDict


# ── Enums / literals ──────────────────────────────────────────────────
RoleLiteral = Literal[
    "Assistant Professor",
    "Associate Professor",
    "Professor",
]
DecisionLiteral = Literal["Retain", "Downgrade", "Reject"]
PathLiteral = Literal["Path A", "Path B"]


# ═══════════════════════════════════════════════════════════════════════
#  CandidateExtractedData  — produced by the READER node (Gemini + Pydantic)
# ═══════════════════════════════════════════════════════════════════════
class CandidateExtractedData(BaseModel):
    """Structured extract of a candidate's resume.

    Filled by Gemini via `.with_structured_output(CandidateExtractedData)`.
    Every field here is a FACT about the resume — no eligibility logic.
    """

    model_config = ConfigDict(
        extra="forbid",          # Reject unknown fields → catches Gemini drift
        validate_assignment=True,
    )

    # ── Identity / contact ────────────────────────────────────────────
    candidate_name: str = Field(..., description="Full name of the candidate as printed on the resume.")
    email: Optional[str] = Field(default=None, description="Candidate contact email, if present on resume.")
    phone: Optional[str] = Field(default=None, description="Candidate contact phone, if present.")

    # ── Applied role (as advertised / parsed from email subject) ─────
    applied_role: RoleLiteral = Field(
        ..., description="The role the candidate applied for, parsed from the application email subject line."
    )

    # ── Degree checklist (AICTE mandatory inputs) ────────────────────
    b_tech: bool = Field(
        default=False,
        description="True if the candidate holds a B.Tech / B.E. (bachelor's in engineering/technology).",
    )
    m_tech: bool = Field(
        default=False,
        description="True if the candidate holds an M.Tech / M.E. (master's in engineering/technology).",
    )
    phd: bool = Field(
        default=False,
        description="True if the candidate has been awarded a Ph.D.",
    )

    # ── First-class status per degree (any one satisfies AICTE) ──────
    b_tech_first_class: bool = Field(
        default=False,
        description="True if B.Tech was awarded with First Class / distinction (≥60% or equivalent CGPA).",
    )
    m_tech_first_class: bool = Field(
        default=False,
        description="True if M.Tech was awarded with First Class / distinction.",
    )
    phd_award_first_class: bool = Field(
        default=False,
        description="True if the qualifying degree leading to / underlying the Ph.D. was First Class. Used for Professor/Associate tiers.",
    )

    # ── Experience (years) ───────────────────────────────────────────
    teaching_experience_years: float = Field(
        default=0.0,
        ge=0,
        description="Total years in teaching / academic positions.",
    )
    research_experience_years: float = Field(
        default=0.0,
        ge=0,
        description="Total years in research positions (post-doc, research scientist, etc.).",
    )
    post_phd_experience_years: float = Field(
        default=0.0,
        ge=0,
        description="Years of experience accrued AFTER the Ph.D. award date.",
    )

    # ── Publications ─────────────────────────────────────────────────
    publications_count: int = Field(
        default=0,
        ge=0,
        description="Total number of peer-reviewed publications (journals / conferences).",
    )
    publications_at_associate_level: int = Field(
        default=0,
        ge=0,
        description="Publications produced while at Associate Professor level (used by Professor Path A).",
    )

    # ── Doctoral supervision ─────────────────────────────────────────
    phd_students_guided: int = Field(
        default=0,
        ge=0,
        description="Number of Ph.D. scholars guided to completion as primary supervisor.",
    )

    # ── Raw tracebacks for the Reporter node ─────────────────────────
    resume_markdown_excerpt: Optional[str] = Field(
        default=None,
        description="A short verbatim excerpt (≤ 500 chars) of the key qualifications section, retained so the Reporter can quote the resume.",
    )

    def total_experience_years(self) -> float:
        """Convenience: teaching + research combined figure used by some rubric tiers."""
        return self.teaching_experience_years + self.research_experience_years


# ═══════════════════════════════════════════════════════════════════════
#  EvaluationResult  — produced by the EVALUATOR node (pure Python, no LLM)
# ═══════════════════════════════════════════════════════════════════════
class EvaluationResult(BaseModel):
    """Deterministic output of the Evaluator node.

    Tier 1  → eligibility decision (Retain / Downgrade / Reject)
              plus the list of failing criteria for auditability.
    Tier 2  → comparative API score (0–100), only meaningful if Retain.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    # ── Tier 1 ────────────────────────────────────────────────────────
    decision: DecisionLiteral = Field(
        ..., description="Final Tier 1 eligibility decision against the applied role."
    )
    applied_role: RoleLiteral = Field(..., description="The role evaluated.")
    qualified_role: Optional[RoleLiteral] = Field(
        default=None,
        description="If decision is 'Downgrade', the highest role the candidate DOES qualify for; otherwise None.",
    )
    satisfied_path: Optional[PathLiteral] = Field(
        default=None,
        description="For 'Professor', which path (A or B) satisfied the criteria, if any."
    )

    # ── Audit trail ──────────────────────────────────────────────────
    failing_criteria: list[str] = Field(
        default_factory=list,
        description="Human-readable list of criteria the candidate failed for the applied role. Empty if Retain."
    )
    downgrade_reason: Optional[str] = Field(
        default=None,
        description="If decision is 'Downgrade', brief reason why downgrade (vs outright reject) was chosen."
    )

    # ── Tier 2 ───────────────────────────────────────────────────────
    comparative_score: float = Field(
        default=0.0,
        ge=0.0,
        le=100.0,
        description="Deterministic weighted score (0–100) for comparative ranking among Retain candidates. 0 if not retained.",
    )
    score_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Per-metric weighted contribution to comparative_score, for transparency."
    )

    # ── Human-in-the-loop safety net ───────────────────────────────────
    needs_review: bool = Field(
        default=False,
        description="True if the extracted resume data looks too sparse/suspicious to trust blindly "
                     "(e.g. almost everything defaulted to False/0). Does not change the decision — "
                     "it just flags the report so a human double-checks the extraction before acting on it.",
    )
    review_reasons: list[str] = Field(
        default_factory=list,
        description="Why needs_review was set, e.g. 'No contact email found on resume'.",
    )

    def is_retain(self) -> bool:
        return self.decision == "Retain"
