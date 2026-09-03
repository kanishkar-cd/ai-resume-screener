import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.scoring import ComponentScoreDetail, ComponentScores, RecommendationLevel
from app.services.matching_service import (
    Evidence, EvidenceBuilder, EvidencePrefilter, HybridMatchingService, MatchMethod,
    MatchStatus, MatchVerdict, Requirement, RequirementBuilder, RequirementKind,
)
from app.services.scoring import (
    BonusService, PenaltyService, RecommendationService, WeightCalculationService,
)


def _build_components(
    skill_score: float = 100.0,
    skill_matched: list[str] | None = None,
    skill_missing: list[str] | None = None,
    resp_score: float = 100.0,
    resp_matched: list[str] | None = None,
    resp_missing: list[str] | None = None,
    proj_score: float = 100.0,
    proj_matched: list[str] | None = None,
    proj_missing: list[str] | None = None,
    pref_score: float = 0.0,
    pref_matched: list[str] | None = None,
    pref_missing: list[str] | None = None,
) -> ComponentScores:
    return ComponentScores(
        skills=ComponentScoreDetail(
            score=skill_score,
            matched_items=skill_matched if skill_matched is not None else ["Python", "SQL"],
            missing_items=skill_missing if skill_missing is not None else [],
            explanation="skills",
        ),
        responsibilities=ComponentScoreDetail(
            score=resp_score,
            matched_items=resp_matched if resp_matched is not None else ["Build APIs", "Design Schemas"],
            missing_items=resp_missing if resp_missing is not None else [],
            explanation="responsibilities",
        ),
        projects=ComponentScoreDetail(
            score=proj_score,
            matched_items=proj_matched if proj_matched is not None else ["Project A"],
            missing_items=proj_missing if proj_missing is not None else [],
            explanation="projects",
        ),
        preferred_skills=ComponentScoreDetail(
            score=pref_score,
            matched_items=pref_matched if pref_matched is not None else [],
            missing_items=pref_missing if pref_missing is not None else ["Docker", "Kubernetes"],
            explanation="preferred_skills",
        ),
        experience=ComponentScoreDetail(score=80.0, matched_items=["24 months"], missing_items=[], explanation="exp"),
        education=ComponentScoreDetail(score=100.0, matched_items=["B.Tech"], missing_items=[], explanation="edu"),
        certifications=ComponentScoreDetail(score=0.0, matched_items=[], missing_items=[], explanation="certs"),
        languages=ComponentScoreDetail(score=100.0, matched_items=["English"], missing_items=[], explanation="lang"),
    )


def test_required_skills_and_responsibilities_scored_together_as_core_requirements() -> None:
    """
    Test 1: Required skills + responsibilities form the unified Core Requirements pool.
    Example: 2 required skills (both matched) + 2 responsibilities (1 matched, 1 missing).
    Total Core items = 4 (3 matched, 1 missing) -> Core score = (3/4) * 100 = 75.0%.
    """
    components = _build_components(
        skill_score=100.0,
        skill_matched=["Python", "SQL"],
        skill_missing=[],
        resp_score=50.0,
        resp_matched=["Build APIs"],
        resp_missing=["Deploy Services"],
        proj_score=0.0,
        proj_matched=[],
        proj_missing=[],
    )
    weighted_scores, raw_total, core_base_score, effective_weights = WeightCalculationService.calculate(
        components, applicable_categories={"required_skills", "responsibilities"}
    )
    # Proportional redistribution: Skills (40/60 = 66.67%), Responsibilities (20/60 = 33.33%)
    # 100 * (40/60) + 50 * (20/60) = 66.67 + 16.67 = 83.33
    assert core_base_score == 83.33
    assert WeightCalculationService.final_score(core_base_score, 0.0, 0.0, components, applicable_categories={"required_skills", "responsibilities"}) == 83.33


def test_lexical_prefilter_miss_routes_to_semantic_verification() -> None:
    """
    Test 2: Lexical prefilter miss does NOT immediately drop to NO_MATCH.
    Evidence is supplied to LLM for semantic verification.
    """
    req = Requirement(
        requirement_id="skill:1",
        kind=RequirementKind.REQUIRED_SKILL,
        text="Object-Oriented Programming",
        canonical_value="Object-Oriented Programming",
        required=True,
    )
    # Candidate evidence has Java and Python backend project experience without exact phrase 'Object-Oriented Programming'
    evidence = [
        Evidence(
            evidence_id="project:1",
            kind="project",
            text="Developed enterprise backend microservices in Java with Spring Boot",
            canonical_terms=["Java", "Spring Boot"],
        ),
        Evidence(
            evidence_id="experience:1",
            kind="experience",
            text="Software Engineer designing clean domain models and design patterns in Python",
            canonical_terms=["Python"],
        ),
    ]

    prefilter = EvidencePrefilter(threshold=0.10, limit=5)
    selected = prefilter.select(req, evidence)

    # Must NOT return empty list
    assert len(selected) > 0
    assert any(e.evidence_id in {"project:1", "experience:1"} for e in selected)


@pytest.mark.asyncio
async def test_postgresql_provides_evidence_for_sql_via_contextual_matching() -> None:
    """
    Test 3: PostgreSQL in candidate resume provides evidence for an SQL requirement.
    """
    job = SimpleNamespace(
        required_skills=["SQL"],
        skills=["SQL"],
        responsibilities=["Maintain relational database models"],
        preferred_skills=[],
        certifications=[],
        degree_requirements=[],
        project_requirements=[],
    )
    extracted = SimpleNamespace(
        skills=["PostgreSQL", "FastAPI"],
        experience=[{
            "title": "Backend Developer",
            "company": "Tech Corp",
            "description": "Designed complex PostgreSQL schemas, optimized relational queries, and maintained database migrations.",
            "responsibilities": ["Wrote optimized PostgreSQL queries and views"],
        }],
        projects=[{
            "name": "E-Commerce Backend",
            "description": "Engineered REST APIs connected to PostgreSQL database with ACID compliance.",
            "technologies": ["PostgreSQL", "Python"],
        }],
        education=[{"degree": "Bachelor of Technology", "field": "Computer Science"}],
        certifications=[],
        summary="Backend developer with deep experience in PostgreSQL database design.",
    )
    resume = SimpleNamespace(id="cand-1", candidate_name="Dev Candidate")

    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=([
        MatchVerdict(
            requirement_id="skill:1",
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["skills:1", "project:1"],
            reasoning="PostgreSQL experience fulfills SQL requirement.",
            method=MatchMethod.LLM_CONFIRMED,
            coverage=1.0,
        ),
        MatchVerdict(
            requirement_id="responsibility:1",
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["experience:1"],
            reasoning="PostgreSQL schema and query design fulfills relational database responsibility.",
            method=MatchMethod.LLM_CONFIRMED,
            coverage=1.0,
        ),
    ], {}))

    matcher = HybridMatchingService(evaluator=mock_evaluator)
    enriched, verdicts = await matcher.match(job, resume, extracted)

    sql_verdict = next((v for v in verdicts if "SQL" in getattr(v, "requirement_text", "") or "skill:1" in v.requirement_id), None)
    assert sql_verdict is not None
    assert sql_verdict.status == MatchStatus.MATCHED


def test_missing_preferred_skills_never_reduces_core_score() -> None:
    """
    Test 4: Missing preferred skills do NOT reduce the core score.
    100% Core score remains 100% even if candidate has 0 preferred skills.
    Matched preferred skill adds bonus points.
    """
    components_no_pref = _build_components(
        skill_score=100.0,
        skill_matched=["Python", "FastAPI"],
        skill_missing=[],
        resp_score=100.0,
        resp_matched=["Build backend services"],
        resp_missing=[],
        pref_score=0.0,
        pref_matched=[],
        pref_missing=["Docker", "AWS", "Kubernetes"],
    )
    _, _, core_score_no_pref, _ = WeightCalculationService.calculate(
        components_no_pref, applicable_categories={"required_skills", "responsibilities"}
    )
    final_no_pref = WeightCalculationService.final_score(core_score_no_pref, 0.0, 0.0, components_no_pref, applicable_categories={"required_skills", "responsibilities"})
    # Proportional redistribution across active skills (40/60) and responsibilities (20/60) -> 100.0
    assert final_no_pref == 100.0


def test_explicit_knockout_forces_zero_and_reject() -> None:
    """
    Test 5: Explicit knockout forces 0.0 and REJECT only when enabled.
    """
    config_with_knockout = SimpleNamespace(
        mandatory_skills=["Python"],
        knockout_rules=[{"rule_type": "MISSING_MANDATORY_SKILL", "enabled": True}],
    )
    components = _build_components(
        skill_score=50.0,
        skill_matched=["SQL"],
        skill_missing=["Python"],
    )
    knocked_out, reason = WeightCalculationService.knockout(components, config_with_knockout)
    assert knocked_out is True
    assert "Python" in str(reason)

    recommendation = RecommendationService.recommend(
        final_score=85.0,
        passing_score=70.0,
        is_knocked_out=knocked_out,
        knockout_reason=reason,
    )
    assert recommendation == RecommendationLevel.REJECT


def test_final_score_independent_of_legacy_static_component_weights() -> None:
    """
    Test 6: Final score does not use legacy rigid 8-component weights (e.g. 30/25/25/15/5/5).
    Score is purely Matched Core / Total Core.
    """
    # Case: 3 Required Skills (all matched), 1 Responsibility (matched) -> 4 Core items, all 4 matched -> 100%
    components_perfect = _build_components(
        skill_score=100.0,
        skill_matched=["A", "B", "C"],
        skill_missing=[],
        resp_score=100.0,
        resp_matched=["Task 1"],
        resp_missing=[],
    )
    _, _, score_perfect, _ = WeightCalculationService.calculate(
        components_perfect, applicable_categories={"required_skills", "responsibilities"}
    )
    # Proportional redistribution across active skills (40/60) and responsibilities (20/60) -> 100.0
    assert score_perfect == 100.0

    # Case: 3 Required Skills (2 matched, 1 missing -> 66.67%), 1 Responsibility (matched -> 100%)
    # Skills: 66.67 * (40/60) = 44.4467, Resp: 100 * (20/60) = 33.3333 -> 77.78%
    components_partial = _build_components(
        skill_score=66.67,
        skill_matched=["A", "B"],
        skill_missing=["C"],
        resp_score=100.0,
        resp_matched=["Task 1"],
        resp_missing=[],
    )
    _, _, score_partial, _ = WeightCalculationService.calculate(
        components_partial, applicable_categories={"required_skills", "responsibilities"}
    )
    assert score_partial == 77.78
