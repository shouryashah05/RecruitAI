"""
Unit tests for the deterministic eligibility/scoring logic in nodes/evaluator.py.
No network, no API keys — this is the one part of the pipeline required to be
hallucination-free, so it's the part most worth covering with tests.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.schemas import CandidateExtractedData
from nodes.evaluator import evaluate_candidate


def make_candidate(**overrides) -> CandidateExtractedData:
    defaults = dict(candidate_name="Test Candidate", applied_role="Assistant Professor")
    defaults.update(overrides)
    return CandidateExtractedData(**defaults)


def test_assistant_professor_retain():
    data = make_candidate(
        applied_role="Assistant Professor",
        b_tech=True, m_tech=True, b_tech_first_class=True,
    )
    result = evaluate_candidate(data)
    assert result.decision == "Retain"
    assert result.qualified_role is None
    assert result.failing_criteria == []


def test_assistant_professor_reject_missing_mtech():
    data = make_candidate(
        applied_role="Assistant Professor",
        b_tech=True, m_tech=False, b_tech_first_class=True,
    )
    result = evaluate_candidate(data)
    assert result.decision == "Reject"
    assert result.comparative_score == 0.0
    assert any("Missing required degree" in c for c in result.failing_criteria)


def test_associate_professor_retain():
    data = make_candidate(
        applied_role="Associate Professor",
        phd=True, phd_award_first_class=True,
        teaching_experience_years=5, research_experience_years=4,
        post_phd_experience_years=3, publications_count=8,
    )
    result = evaluate_candidate(data)
    assert result.decision == "Retain"
    assert result.comparative_score > 0


def test_associate_professor_downgrades_to_assistant():
    data = make_candidate(
        applied_role="Associate Professor",
        phd=True, phd_award_first_class=True,
        teaching_experience_years=1, publications_count=1,  # too little for Associate
        b_tech=True, m_tech=True, b_tech_first_class=True,   # but qualifies for Assistant
    )
    result = evaluate_candidate(data)
    assert result.decision == "Downgrade"
    assert result.qualified_role == "Assistant Professor"
    assert result.comparative_score > 0


def test_professor_retain_via_path_a():
    data = make_candidate(
        applied_role="Professor",
        phd=True, phd_award_first_class=True,
        teaching_experience_years=6, research_experience_years=5,
        publications_at_associate_level=6, phd_students_guided=2,
    )
    result = evaluate_candidate(data)
    assert result.decision == "Retain"
    assert result.satisfied_path == "Path A"


def test_professor_retain_via_path_b():
    data = make_candidate(
        applied_role="Professor",
        phd=True, phd_award_first_class=True,
        teaching_experience_years=10, publications_count=12,
    )
    result = evaluate_candidate(data)
    assert result.decision == "Retain"
    assert result.satisfied_path == "Path B"


def test_professor_downgrades_to_associate():
    data = make_candidate(
        applied_role="Professor",
        phd=True, phd_award_first_class=True,
        teaching_experience_years=5, research_experience_years=3,  # 8 total: meets Associate, not Professor's 10
        post_phd_experience_years=2, publications_count=7,
    )
    result = evaluate_candidate(data)
    assert result.decision == "Downgrade"
    assert result.qualified_role == "Associate Professor"


def test_outright_reject_no_lower_role_qualifies():
    data = make_candidate(applied_role="Professor")  # everything defaulted to False/0
    result = evaluate_candidate(data)
    assert result.decision == "Reject"
    assert result.qualified_role is None
    assert result.comparative_score == 0.0


def test_needs_review_flags_sparse_extraction():
    data = make_candidate(applied_role="Assistant Professor", email=None)
    result = evaluate_candidate(data)
    assert result.needs_review is True
    assert len(result.review_reasons) > 0


def test_score_breakdown_sums_to_comparative_score():
    data = make_candidate(
        applied_role="Associate Professor",
        phd=True, phd_award_first_class=True,
        teaching_experience_years=5, research_experience_years=4,
        post_phd_experience_years=3, publications_count=8, phd_students_guided=3,
    )
    result = evaluate_candidate(data)
    assert round(sum(result.score_breakdown.values()), 2) == result.comparative_score
