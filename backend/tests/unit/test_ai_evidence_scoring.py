import pytest
from types import SimpleNamespace
from app.schemas.matching import (
    Requirement, RequirementKind, Evidence, MatchStatus, MatchVerdict, MatchMethod, LLMVerdictBatch, LLMVerdict
)
from app.services.matching_service import EvidenceBuilder, GroqMatchEvaluator
from app.schemas.scoring import ComponentScores, ComponentScoreDetail
from app.services.scoring.weight_calculation_service import WeightCalculationService


def test_evidence_builder_extracts_all_types() -> None:
    extracted = SimpleNamespace(
        projects=[{"name": "E-Commerce", "description": "Built React app", "technologies": ["React", "Node"]}],
        experience=[{"title": "Software Engineer", "company": "Tech Corp", "description": "Built FastAPI services", "responsibilities": ["API design"]}],
        skills=["Python", "FastAPI", "Docker"],
        education=[{"degree": "Bachelor of Science", "field_of_study": "Computer Science", "institution": "State University"}],
        certifications=["AWS Certified Solutions Architect"],
        languages=["English", "Spanish"]
    )
    evidence = EvidenceBuilder.build(extracted)
    evidence_ids = {e.evidence_id for e in evidence}
    
    assert "project:1" in evidence_ids
    assert "experience:1" in evidence_ids
    assert "skills:1" in evidence_ids
    assert "education:1" in evidence_ids
    assert "certification:1" in evidence_ids
    assert "languages:1" in evidence_ids


def test_groq_evaluator_validation_rejects_hallucinated_evidence_ids() -> None:
    evaluator = GroqMatchEvaluator()
    requirements = [Requirement(requirement_id="resp:1", kind=RequirementKind.RESPONSIBILITY, text="Build scalable microservices")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Software Engineer at Tech Corp - Built FastAPI microservices")]
    
    # LLM returns an invalid evidence_id not present in supplied evidence
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="resp:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:999"], reasoning="Good match")
    ])
    
    validated = evaluator._validate(batch, requirements, evidence)
    assert len(validated) == 1
    # Invalid evidence ID causes confirmed to be False -> UNRESOLVED
    assert validated[0].status == MatchStatus.UNRESOLVED
    assert validated[0].evidence_ids == []


def test_groq_evaluator_accepts_valid_evidence_and_high_confidence() -> None:
    evaluator = GroqMatchEvaluator()
    requirements = [Requirement(requirement_id="resp:1", kind=RequirementKind.RESPONSIBILITY, text="Build scalable microservices")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Software Engineer at Tech Corp - Built FastAPI microservices")]
    
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="resp:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], reasoning="Direct evidence found")
    ])
    
    validated = evaluator._validate(batch, requirements, evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert validated[0].evidence_ids == ["experience:1"]


def test_scoring_formula_na_and_partial_evidence() -> None:
    job = SimpleNamespace(
        required_skills=["Python", "FastAPI"],
        experience_requirements=[{"minimum_months": 48}],
    )
    skills = ComponentScoreDetail(score=100.0, matched_items=["Python", "FastAPI"], missing_items=[], explanation="Matched.")
    exp = ComponentScoreDetail(score=50.0, matched_items=["24 months"], missing_items=["24 months"], explanation="Partial experience.")
    na = ComponentScoreDetail(score=100.0, matched_items=[], missing_items=[], explanation="No specific requirement (N/A).")
    components = ComponentScores(
        skills=skills, experience=exp, projects=na,
        education=na, certifications=na, languages=na,
    )
    applicable = WeightCalculationService.applicable_categories(job)
    final_score = WeightCalculationService.final_score(75.0, 0.0, 0.0, components, applicable)
    
    # Skills (100% of 30 = 30) + Experience (50% of 5 = 2.5) = 32.5 / 35 -> Normalized: 92.86
    assert final_score == 92.86
