"""
evaluator.py — deterministic Tier 1 (eligibility) + Tier 2 (comparative score) logic.

Everything here is pure Python driven by config/aicte_rubric.json. The LLM is
never consulted for pass/fail decisions or scoring — only the Reader node uses
AI, and only to turn a resume into the CandidateExtractedData facts this file
then checks mechanically. That keeps eligibility matching hallucination-free.
"""
import json
import os
from functools import lru_cache
from typing import Optional

from core.schemas import CandidateExtractedData, EvaluationResult, RoleLiteral

# Faculty roles ordered from lowest to highest seniority. Downgrade logic walks
# backwards through this list to find the highest role the candidate actually
# qualifies for.
ROLE_ORDER: list[RoleLiteral] = ["Assistant Professor", "Associate Professor", "Professor"]

# Path A's "publications_required" in the rubric refers to publications earned
# specifically at Associate level, not lifetime total — the rubric documents
# this via a free-text "publications_context" field, so it's special-cased here.
PROFESSOR_PATH_PUBLICATION_FIELD = {
    "Path A": "publications_at_associate_level",
    "Path B": "publications_count",
}


@lru_cache(maxsize=1)
def load_rubric() -> dict:
    rubric_path = os.path.join(os.path.dirname(__file__), "..", "config", "aicte_rubric.json")
    with open(rubric_path, "r", encoding="utf-8") as f:
        return json.load(f)


def _has_first_class(data: CandidateExtractedData, condition: dict) -> bool:
    values = [bool(getattr(data, field, False)) for field in condition.get("fields", [])]
    if condition.get("operator", "OR").upper() == "AND":
        return all(values)
    return any(values)


def _check_simple_role(data: CandidateExtractedData, role_def: dict) -> tuple[bool, list[str]]:
    """Assistant Professor / Associate Professor style requirement block."""
    failing: list[str] = []

    for degree, required in role_def.get("required_degrees", {}).items():
        if required and not getattr(data, degree, False):
            failing.append(f"Missing required degree: {degree.replace('_', ' ').upper()}")

    if not _has_first_class(data, role_def.get("first_class_condition", {})):
        failing.append(role_def.get("first_class_rule", "Missing required First Class degree"))

    exp_required = role_def.get("experience_years_required", 0)
    if data.total_experience_years() < exp_required:
        failing.append(
            f"Insufficient total experience: {data.total_experience_years():.1f} yrs "
            f"(needs {exp_required} yrs)"
        )

    post_phd_required = role_def.get("post_phd_experience_years_required", 0)
    if data.post_phd_experience_years < post_phd_required:
        failing.append(
            f"Insufficient post-Ph.D. experience: {data.post_phd_experience_years:.1f} yrs "
            f"(needs {post_phd_required} yrs)"
        )

    pubs_required = role_def.get("publications_required", 0)
    if data.publications_count < pubs_required:
        failing.append(
            f"Insufficient publications: {data.publications_count} (needs {pubs_required})"
        )

    guided_required = role_def.get("phd_students_guided_required", 0)
    if data.phd_students_guided < guided_required:
        failing.append(
            f"Insufficient Ph.D. students guided: {data.phd_students_guided} (needs {guided_required})"
        )

    return (len(failing) == 0), failing


def _check_professor(data: CandidateExtractedData, role_def: dict) -> tuple[bool, list[str], Optional[str]]:
    """Professor requires satisfying Path A OR Path B. Returns (passed, failing_of_best_path, path_name)."""
    best_failing: list[str] = []
    for path_name, path_def in role_def.get("paths", {}).items():
        failing: list[str] = []

        for degree, required in path_def.get("required_degrees", {}).items():
            if required and not getattr(data, degree, False):
                failing.append(f"[{path_name}] Missing required degree: {degree.replace('_', ' ').upper()}")

        if not _has_first_class(data, path_def.get("first_class_condition", {})):
            failing.append(f"[{path_name}] {path_def.get('first_class_rule', 'Missing required First Class degree')}")

        exp_required = path_def.get("experience_years_required", 0)
        if data.total_experience_years() < exp_required:
            failing.append(
                f"[{path_name}] Insufficient total experience: {data.total_experience_years():.1f} yrs "
                f"(needs {exp_required} yrs)"
            )

        pub_field = PROFESSOR_PATH_PUBLICATION_FIELD.get(path_name, "publications_count")
        pub_value = getattr(data, pub_field, 0)
        pubs_required = path_def.get("publications_required", 0)
        if pub_value < pubs_required:
            failing.append(f"[{path_name}] Insufficient publications: {pub_value} (needs {pubs_required})")

        guided_required = path_def.get("phd_students_guided_required", 0)
        if data.phd_students_guided < guided_required:
            failing.append(
                f"[{path_name}] Insufficient Ph.D. students guided: "
                f"{data.phd_students_guided} (needs {guided_required})"
            )

        if not failing:
            return True, [], path_name

        if not best_failing or len(failing) < len(best_failing):
            best_failing = failing

    return False, best_failing, None


def check_role_eligibility(
    data: CandidateExtractedData, role: str, rubric: dict
) -> tuple[bool, list[str], Optional[str]]:
    """Returns (passed, failing_criteria, satisfied_path). satisfied_path is only set for Professor."""
    role_def = rubric.get("roles", {}).get(role)
    if role_def is None:
        return False, [f"Unknown role '{role}' in rubric"], None

    if role == "Professor":
        return _check_professor(data, role_def)

    passed, failing = _check_simple_role(data, role_def)
    return passed, failing, None


def assess_confidence(data: CandidateExtractedData) -> tuple[bool, list[str]]:
    """
    Flags resumes whose extraction looks too sparse/suspicious to trust blindly.
    This is a human-in-the-loop safety net around the LLM extraction step (the
    one place in the pipeline that CAN hallucinate) — it never touches the
    deterministic eligibility decision itself.
    """
    reasons: list[str] = []

    if not data.email:
        reasons.append("No contact email found on resume")

    no_degrees = not (data.b_tech or data.m_tech or data.phd)
    no_experience = data.total_experience_years() == 0
    no_publications = data.publications_count == 0
    if no_degrees and no_experience and no_publications:
        reasons.append("Extraction returned almost no qualification data (no degrees, experience, or publications)")

    if not data.candidate_name or not data.candidate_name.strip():
        reasons.append("No candidate name extracted")

    return (len(reasons) > 0), reasons


def calculate_comparative_score(data: CandidateExtractedData, rubric: dict) -> tuple[float, dict[str, float]]:
    """
    Tier 2 ranking score (0-100), computed from the rubric's declared weights
    and benchmarks so config/aicte_rubric.json stays the single source of
    truth (not just documentation next to a disconnected hardcoded formula).
    """
    tier2 = rubric.get("tier2_comparative_scoring", {})
    weights = tier2.get("weights", {})
    benchmarks = tier2.get("benchmarks", {})
    max_score = tier2.get("max_score", 100)

    metric_values = {
        "teaching_experience_years": data.teaching_experience_years,
        "research_experience_years": data.research_experience_years,
        "publications_count": data.publications_count,
        "phd_awarded": 1.0 if data.phd else 0.0,
        "phd_students_guided": data.phd_students_guided,
        "first_class_count": sum(
            [data.b_tech_first_class, data.m_tech_first_class, data.phd_award_first_class]
        ),
    }

    breakdown: dict[str, float] = {}
    total = 0.0
    for metric, weight in weights.items():
        benchmark = benchmarks.get(metric, 1) or 1
        normalized = min(metric_values.get(metric, 0) / benchmark, 1.0)
        contribution = round(normalized * weight * max_score, 2)
        breakdown[metric] = contribution
        total += contribution

    return min(round(total, 2), float(max_score)), breakdown


def evaluate_candidate(data: CandidateExtractedData) -> EvaluationResult:
    """
    Tier 1: check the applied role; if it fails, cascade DOWN through lower
    roles and downgrade to the highest one the candidate actually qualifies
    for (e.g. fails Professor but qualifies for Assistant Professor -> Downgrade).
    Tier 2: comparative score, computed whenever the candidate is Retained or
    Downgraded into some role (not meaningful for an outright Reject).
    """
    rubric = load_rubric()
    applied_role = data.applied_role

    passed, failing_criteria, satisfied_path = check_role_eligibility(data, applied_role, rubric)

    decision = "Reject"
    qualified_role: Optional[str] = None
    downgrade_reason: Optional[str] = None

    if passed:
        decision = "Retain"
    else:
        applied_index = ROLE_ORDER.index(applied_role) if applied_role in ROLE_ORDER else -1
        for lower_role in reversed(ROLE_ORDER[:applied_index]):
            lower_passed, _, lower_path = check_role_eligibility(data, lower_role, rubric)
            if lower_passed:
                decision = "Downgrade"
                qualified_role = lower_role
                satisfied_path = lower_path
                downgrade_reason = (
                    f"Does not meet '{applied_role}' requirements, but fully qualifies for "
                    f"'{lower_role}'. Failing criteria for {applied_role}: {'; '.join(failing_criteria)}"
                )
                break
        if decision == "Reject":
            downgrade_reason = f"Does not meet minimum requirements for any role. Failing criteria: {'; '.join(failing_criteria)}"

    if decision == "Reject":
        comparative_score, score_breakdown = 0.0, {}
    else:
        comparative_score, score_breakdown = calculate_comparative_score(data, rubric)

    needs_review, review_reasons = assess_confidence(data)

    return EvaluationResult(
        decision=decision,
        applied_role=applied_role,
        qualified_role=qualified_role,
        satisfied_path=satisfied_path,
        failing_criteria=failing_criteria if decision != "Retain" else [],
        downgrade_reason=downgrade_reason,
        comparative_score=comparative_score,
        score_breakdown=score_breakdown,
        needs_review=needs_review,
        review_reasons=review_reasons,
    )
