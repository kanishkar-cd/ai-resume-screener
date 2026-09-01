from types import SimpleNamespace
import pytest

from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchStatus, Requirement, RequirementKind, MatchVerdict, MatchMethod,
)
from app.services.matching_service import (
    ALLOWED_EVIDENCE_MAP, DeterministicRequirementMatcher, EvidencePrefilter,
    GroqMatchEvaluator, is_entity_compatible,
)


def test_1_education_requirement_plus_education_evidence():
    """TEST 1: Education requirement + education evidence -> MATCHED when valid."""
    req = Requirement(requirement_id="degree:1", kind=RequirementKind.DEGREE, text="Bachelor's Degree in Computer Science")
    resume = SimpleNamespace(
        education=[{"degree": "Bachelor of Technology", "field": "Computer Science", "institution": "IIT"}]
    )
    evidence = [
        Evidence(evidence_id="education:1", kind="education", text="Bachelor of Technology in Computer Science from IIT")
    ]
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert "education:1" in verdict.evidence_ids


def test_2_education_requirement_plus_experience_evidence_rejected():
    """TEST 2: Education requirement + experience evidence mentioning degree -> NOT MATCHED."""
    req = Requirement(requirement_id="degree:1", kind=RequirementKind.DEGREE, text="Bachelor's Degree in Computer Science")
    resume = SimpleNamespace(
        education=[],
        experience=[{"title": "Software Engineer", "description": "Worked on bachelor's degree verification software."}]
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Software Engineer: Worked on bachelor's degree verification software.")
    ]
    # Check prefilter isolation
    prefilter = EvidencePrefilter(0.1, 5)
    filtered_evidence = prefilter.select(req, evidence)
    assert filtered_evidence == []

    # Check deterministic matcher isolation
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status != MatchStatus.MATCHED
    assert "experience:1" not in verdict.evidence_ids


def test_3_education_requirement_plus_project_evidence_rejected():
    """TEST 3: Education requirement + project evidence -> NOT MATCHED."""
    req = Requirement(requirement_id="degree:1", kind=RequirementKind.DEGREE, text="Bachelor's Degree")
    resume = SimpleNamespace(
        education=[],
        projects=[{"name": "University Degree App", "description": "Built degree tracking app"}]
    )
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="University Degree App: Built degree tracking app")
    ]
    prefilter = EvidencePrefilter(0.1, 5)
    filtered_evidence = prefilter.select(req, evidence)
    assert filtered_evidence == []

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status != MatchStatus.MATCHED
    assert "project:1" not in verdict.evidence_ids


def test_4_experience_requirement_plus_experience_evidence():
    """TEST 4: Experience requirement + experience evidence -> MATCHED when valid."""
    req = Requirement(requirement_id="exp:1", kind=RequirementKind.EXPERIENCE, text="5 years of experience")
    resume = SimpleNamespace(
        experience=[{"title": "Senior Engineer", "duration_months": 65}]
    )
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Senior Engineer 65 months")
    ]
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert "experience:1" in verdict.evidence_ids


def test_5_experience_requirement_plus_education_evidence_rejected():
    """TEST 5: Experience requirement + education evidence -> NOT MATCHED."""
    req = Requirement(requirement_id="exp:1", kind=RequirementKind.EXPERIENCE, text="5 years of React experience")
    resume = SimpleNamespace(
        experience=[],
        education=[{"degree": "B.Tech", "description": "Completed 5 years of React coursework"}]
    )
    evidence = [
        Evidence(evidence_id="education:1", kind="education", text="B.Tech: Completed 5 years of React coursework")
    ]
    # Check prefilter isolation
    prefilter = EvidencePrefilter(0.1, 5)
    filtered_evidence = prefilter.select(req, evidence)
    assert filtered_evidence == []

    # Check compatibility helper
    assert not is_entity_compatible(RequirementKind.EXPERIENCE, "education")


def test_6_experience_requirement_project_allowed_but_education_forbidden():
    """TEST 6: Experience requirement allows experience but forbids education."""
    assert is_entity_compatible(RequirementKind.EXPERIENCE, "experience")
    assert not is_entity_compatible(RequirementKind.EXPERIENCE, "education")
    assert not is_entity_compatible(RequirementKind.DEGREE, "experience")
    assert not is_entity_compatible(RequirementKind.DEGREE, "project")


def test_7_llm_returns_matched_for_education_using_experience_rejected_by_validator():
    """TEST 7: LLM returns MATCHED for education using experience evidence -> Backend validator rejects it."""
    evaluator = GroqMatchEvaluator()
    req = Requirement(requirement_id="degree:1", kind=RequirementKind.DEGREE, text="Bachelor's Degree in Computer Science")
    evidence = [
        Evidence(evidence_id="experience:1", kind="experience", text="Worked on Computer Science degree portal")
    ]
    # Simulate LLM returning MATCHED citing experience:1
    llm_raw_batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(
            requirement_id="degree:1",
            status="MATCHED",
            confidence=0.95,
            evidence_ids=["experience:1"],
            reasoning="Candidate worked on CS degree system.",
        )
    ])
    validated = evaluator._validate(llm_raw_batch, [req], evidence)
    assert len(validated) == 1
    assert validated[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}
    assert "experience:1" not in validated[0].evidence_ids
    assert "cross_entity_evidence_forbidden" in validated[0].reasoning


def test_8_llm_returns_matched_for_experience_using_education_rejected_by_validator():
    """TEST 8: LLM returns MATCHED for experience using education evidence -> Backend validator rejects it."""
    evaluator = GroqMatchEvaluator()
    req = Requirement(requirement_id="exp:1", kind=RequirementKind.EXPERIENCE, text="5 years of Node.js experience")
    evidence = [
        Evidence(evidence_id="education:1", kind="education", text="B.Tech in Node.js Development")
    ]
    llm_raw_batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(
            requirement_id="exp:1",
            status="MATCHED",
            confidence=0.90,
            evidence_ids=["education:1"],
            reasoning="Candidate studied Node.js in degree.",
        )
    ])
    validated = evaluator._validate(llm_raw_batch, [req], evidence)
    assert len(validated) == 1
    assert validated[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}
    assert "education:1" not in validated[0].evidence_ids


def test_9_education_requirement_with_no_education_evidence():
    """TEST 9: Education requirement with no education evidence -> UNRESOLVED / NO_MATCH."""
    req = Requirement(requirement_id="degree:1", kind=RequirementKind.DEGREE, text="Master's Degree")
    resume = SimpleNamespace(education=[])
    evidence = []
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}
    assert verdict.evidence_ids == []


def test_10_experience_requirement_with_insufficient_experience():
    """TEST 10: Experience requirement with insufficient experience -> UNRESOLVED / NO_MATCH."""
    req = Requirement(requirement_id="exp:1", kind=RequirementKind.EXPERIENCE, text="60 months required")
    resume = SimpleNamespace(experience=[{"title": "Junior Dev", "duration_months": 24}])
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Junior Dev 24 months")]
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.UNRESOLVED
    assert "below required" in verdict.reasoning


def test_11_education_and_experience_evidence_isolated():
    """TEST 11: Education and experience evidence both exist -> each requirement sees ONLY its compatible evidence."""
    req_deg = Requirement(requirement_id="degree:1", kind=RequirementKind.DEGREE, text="Bachelor's Degree")
    req_exp = Requirement(requirement_id="exp:1", kind=RequirementKind.EXPERIENCE, text="3 years of experience")
    evidence = [
        Evidence(evidence_id="education:1", kind="education", text="B.Tech in Computer Science"),
        Evidence(evidence_id="experience:1", kind="experience", text="Software Engineer 36 months"),
    ]
    prefilter = EvidencePrefilter(0.1, 5)

    deg_prefiltered = prefilter.select(req_deg, evidence)
    assert all(e.kind == "education" for e in deg_prefiltered)
    assert not any(e.kind == "experience" for e in deg_prefiltered)

    exp_prefiltered = prefilter.select(req_exp, evidence)
    assert all(e.kind in {"experience", "internship"} for e in exp_prefiltered)
    assert not any(e.kind == "education" for e in exp_prefiltered)


def test_12_matrix_integrity():
    """TEST 12: Verify complete matrix compatibility enforcement."""
    assert is_entity_compatible(RequirementKind.DEGREE, "education") is True
    assert is_entity_compatible(RequirementKind.DEGREE, "experience") is False
    assert is_entity_compatible(RequirementKind.DEGREE, "project") is False
    assert is_entity_compatible(RequirementKind.DEGREE, "skills") is False

    assert is_entity_compatible(RequirementKind.EXPERIENCE, "experience") is True
    assert is_entity_compatible(RequirementKind.EXPERIENCE, "education") is False

    assert is_entity_compatible(RequirementKind.CERTIFICATION, "certification") is True
    assert is_entity_compatible(RequirementKind.CERTIFICATION, "education") is False
