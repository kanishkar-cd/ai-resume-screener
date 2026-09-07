import pytest
from decimal import Decimal
from types import SimpleNamespace

from app.models.weight_config import WeightConfigModel, DEFAULT_PASSING_SCORE
from app.schemas.weight_config import WeightConfigCreate
from app.schemas.scoring import CandidateScoreCreate, RecommendationLevel
from app.models.scoring import CandidateScoreModel
from app.services.scoring.recommendation_service import RecommendationService, SHORTLIST_COMPONENT_THRESHOLD
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService
from app.schemas.matching import (
    Evidence,
    Requirement,
    RequirementKind,
    MatchStatus,
    MatchMethod,
    LLMVerdictBatch,
    LLMVerdict,
)
from app.services.matching_service import (
    EvidencePrefilter,
    SemanticEvidenceRetriever,
    GroqMatchEvaluator,
)
from app.core.config import get_settings


def test_issue1_threshold_single_source_of_truth():
    """Issue 1: Ensure WeightConfigModel is single source of truth for DEFAULT_PASSING_SCORE (60.0)."""
    assert DEFAULT_PASSING_SCORE == 60.0
    col_wc = WeightConfigModel.__table__.columns["passing_score"]
    assert float(col_wc.default.arg) == 60.0
    assert WeightConfigCreate().passing_score == 60.0
    assert CandidateScoreCreate.model_fields["passing_score"].default == 60.0

    # Model default is Decimal(60.0)
    col = CandidateScoreModel.__table__.columns["passing_score"]
    assert float(col.default.arg) == 60.0


def test_issue2_shortlist_threshold_proportional_scaling():
    """Issue 2: Shortlist threshold must scale proportionally with passing_score in both component and absolute mode."""
    # When passing_score is 60.0 (default), shortlist threshold is 50.0%
    comps_55 = SimpleNamespace(
        skills=SimpleNamespace(score=55.0, matched_items=["Python"], missing_items=[]),
        responsibilities=SimpleNamespace(score=55.0, matched_items=["APIs"], missing_items=[]),
        education=SimpleNamespace(score=100.0, matched_items=["B.S."], missing_items=[]),
    )
    level_60, _ = RecommendationService.evaluate(
        comps_55,
        effective_weights={"required_skills": 40.0, "responsibilities": 40.0, "education": 20.0},
        applicable_categories={"required_skills", "responsibilities", "education"},
        passing_score=60.0,
    )
    # 55.0 >= 50.0 (shortlist threshold at passing_score 60) and education > 0 -> SHORTLIST
    assert level_60 == RecommendationLevel.SHORTLIST

    # When passing_score is increased to 80.0, shortlist threshold scales up:
    # 80.0 * (50.0 / 60.0) = 66.67%
    # 55.0 is below 66.67% -> must NOT be SHORTLIST
    level_80, _ = RecommendationService.evaluate(
        comps_55,
        effective_weights={"required_skills": 40.0, "responsibilities": 40.0, "education": 20.0},
        applicable_categories={"required_skills", "responsibilities", "education"},
        passing_score=80.0,
    )
    assert level_80 != RecommendationLevel.SHORTLIST

    # In Absolute Mode:
    rec_abs_60 = RecommendationService.recommend(86.0, passing_score=60.0, use_absolute_thresholds=True)
    assert rec_abs_60 == RecommendationLevel.SHORTLIST

    # When passing_score is 80.0, absolute shortlist scales up to 85.0 * (80.0 / 70.0) = 97.14%
    rec_abs_80 = RecommendationService.recommend(86.0, passing_score=80.0, use_absolute_thresholds=True)
    assert rec_abs_80 != RecommendationLevel.SHORTLIST


def test_issue3_lexical_prefilter_semantic_dense_cosine_fallback():
    """Issue 3: EvidencePrefilter rescues chunks failing 0.15 lexical threshold if cosine similarity >= 0.30."""
    prefilter = EvidencePrefilter(threshold=0.15, limit=5)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="relational database schema design")
    # Low exact token overlap with requirement, but strong semantic embedding similarity
    ev = Evidence(
        evidence_id="exp:1",
        kind="experience",
        text="Architected and normalized PostgreSQL SQL tables, indexes, and primary key relationships for large datasets.",
    )
    # Verify semantic cosine similarity meets dense rescue threshold (>= 0.20)
    cos_sim = SemanticEvidenceRetriever.cosine_similarity(req.text, ev.text)
    assert cos_sim >= 0.20

    # Prefilter selection rescues the evidence item via dense cosine fallback
    selected = prefilter.select(req, [ev])
    assert any(e.evidence_id == "exp:1" for e in selected)


def test_issue4_knockout_and_safeguard_relationship():
    """Issue 4: Safeguard caps numerical score (<=35%) and knockout rejects candidate with missing mandatory skill."""
    config = SimpleNamespace(
        mandatory_skills=["Kubernetes"],
        min_experience_years=0,
        knockout_rules=[{"rule_type": "MISSING_MANDATORY_SKILL", "enabled": True}],
    )
    # Candidate with 0% skills but 100% responsibilities
    components = SimpleNamespace(
        skills=SimpleNamespace(score=0.0, matched_items=[], missing_items=["Kubernetes"]),
        responsibilities=SimpleNamespace(score=100.0, matched_items=[], missing_items=[]),
    )
    # 1. Numerical safeguard caps score <= 35.0%
    final_s = WeightCalculationService.final_score(
        weighted_total=50.0,
        penalty_total=0.0,
        bonus_total=0.0,
        components=components,
        applicable_categories={"required_skills", "responsibilities"},
    )
    assert final_s <= 35.0

    # 2. Categorical knockout enforces rejection
    is_knocked_out, reason = WeightCalculationService.knockout(components, config)
    assert is_knocked_out is True
    assert "Kubernetes" in reason


def test_issue5_low_confidence_llm_verdict_explicitly_rejected(caplog):
    """Issue 5: LLM verdicts below confidence threshold (0.80) are explicitly set to NO_MATCH with warning log."""
    evaluator = GroqMatchEvaluator()
    req = Requirement(requirement_id="resp:1", kind=RequirementKind.RESPONSIBILITY, text="Deploy microservices with Kubernetes")
    ev = Evidence(evidence_id="project:1", kind="project", text="Deployed web app to cloud servers")

    # LLM says MATCHED but confidence is 0.72 (< 0.80 threshold)
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(
            requirement_id="resp:1",
            status=MatchStatus.MATCHED,
            confidence=0.72,
            evidence_ids=["project:1"],
            reasoning="Candidate has cloud deployment familiarity.",
        )
    ])

    verdicts = evaluator._validate(batch, [req], [ev], allowed_evidence={"resp:1": {"project:1"}})
    assert len(verdicts) == 1
    # Must be explicitly NO_MATCH, NOT UNRESOLVED
    assert verdicts[0].status == MatchStatus.NO_MATCH
    assert verdicts[0].method == MatchMethod.LLM_REJECTED
    assert verdicts[0].coverage == 0.0
    assert "low confidence" in verdicts[0].reasoning.lower()


def test_issue6_multiword_concept_delimiter_isolation():
    """Issue 6: Multi-word skill concepts must not falsely match across clause delimiters (commas, semicolons)."""
    scorer = ComponentScoringService()

    # Negative case: "Machine" and "Learning" are in separate comma-delimited items
    text_separated = "State Machine, Python, Deep Neural Networks, Learning Management"
    assert scorer._match_multiword_concept("Machine Learning", text_separated) is None

    # Negative case: "REST" and "API" separated by clause delimiter
    text_separated_rest = "RESTful architecture; API gateway"
    # Even though both words exist in the overall resume, across delimiters they are distinct clauses
    assert scorer._match_multiword_concept("REST API", "Took a REST, built an API") is None

    # Positive case: "Machine Learning" together in same clause
    text_together = "Worked on Machine Learning models with TensorFlow and Python."
    assert scorer._match_multiword_concept("Machine Learning", text_together) is not None
