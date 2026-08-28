import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, EvidencePrefilter,
    HybridMatchingService, RequirementBuilder,
)
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import COMPONENT_WEIGHTS, WeightCalculationService


def test_scenario_a_deterministic_match_does_not_call_llm():
    """Scenario A: Deterministic match succeeds -> LLM is never called."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React.js", canonical_value="React.js")
    resume = SimpleNamespace(skills=["React"], experience=[], education=[], certifications=[], languages=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="React", canonical_terms=["React"])]

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.method in {MatchMethod.EXACT, MatchMethod.ALIAS}


def test_scenario_b_semantic_experience_match_triggers_llm():
    """Scenario B: Deterministic miss + relevant experience evidence -> LLM called -> semantic match."""
    job = SimpleNamespace(required_skills=["performance tuning"], skills=["performance tuning"])
    resume = SimpleNamespace(
        skills=["Node.js", "MongoDB"],
        experience=[{
            "title": "Backend Engineer",
            "company": "Tech Corp",
            "description": "Tuned MongoDB database latency and optimized memory bottlenecks.",
            "technologies": ["MongoDB", "Node.js"],
        }],
        projects=[], education=[], certifications=[], languages=[],
    )
    extracted = SimpleNamespace(
        skills=["Node.js", "MongoDB"],
        experience=[{
            "title": "Backend Engineer",
            "company": "Tech Corp",
            "description": "Tuned MongoDB database latency and optimized memory bottlenecks.",
            "technologies": ["MongoDB", "Node.js"],
        }],
        projects=[], education=[], certifications=[], languages=[],
    )

    mock_llm_evaluator = AsyncMock()
    mock_llm_evaluator.evaluate.return_value = [
        MatchVerdict(
            requirement_id="skill:1",
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["experience:1"],
            reasoning="Candidate tuned database performance in experience.",
            method=MatchMethod.LLM_CONFIRMED,
        )
    ]

    service = HybridMatchingService(evaluator=mock_llm_evaluator)
    enriched, verdicts = pytest.importorskip("asyncio").run(service.match(job, resume, extracted, config=None))

    assert mock_llm_evaluator.evaluate.called
    skill_verdict = next((v for v in verdicts if v.requirement_id == "skill:1"), None)
    assert skill_verdict is not None
    assert skill_verdict.status == MatchStatus.MATCHED
    assert skill_verdict.method == MatchMethod.LLM_CONFIRMED


def test_scenario_c_semantic_project_match():
    """Scenario C: Deterministic miss + relevant project evidence -> LLM called -> semantic match."""
    job = SimpleNamespace(required_skills=["state management"], skills=["state management"])
    resume = SimpleNamespace(
        skills=["React"],
        experience=[],
        projects=[{
            "name": "E-Commerce Web App",
            "description": "Architected centralized application state and event-driven data flow across components using Redux.",
            "technologies": ["React", "Redux"],
        }],
        education=[], certifications=[], languages=[],
    )
    extracted = SimpleNamespace(
        skills=["React"],
        experience=[],
        projects=[{
            "name": "E-Commerce Web App",
            "description": "Architected centralized application state and event-driven data flow across components using Redux.",
            "technologies": ["React", "Redux"],
        }],
        education=[], certifications=[], languages=[],
    )

    mock_llm_evaluator = AsyncMock()
    mock_llm_evaluator.evaluate.return_value = [
        MatchVerdict(
            requirement_id="skill:1",
            status=MatchStatus.MATCHED,
            confidence=0.90,
            evidence_ids=["project:1"],
            reasoning="Demonstrated state management in Redux project.",
            method=MatchMethod.LLM_CONFIRMED,
        )
    ]

    service = HybridMatchingService(evaluator=mock_llm_evaluator)
    enriched, verdicts = pytest.importorskip("asyncio").run(service.match(job, resume, extracted, config=None))

    assert mock_llm_evaluator.evaluate.called
    skill_verdict = next((v for v in verdicts if v.requirement_id == "skill:1"), None)
    assert skill_verdict is not None
    assert skill_verdict.status == MatchStatus.MATCHED


def test_scenario_d_no_evidence_does_not_call_llm():
    """Scenario D: Deterministic miss with zero relevant evidence -> LLM is NOT called -> final UNMET."""
    job = SimpleNamespace(required_skills=["Jest"], skills=["Jest"])
    resume = SimpleNamespace(
        skills=["Python", "FastAPI"],
        experience=[{"description": "Built database APIs"}],
        projects=[], education=[], certifications=[], languages=[],
    )
    extracted = SimpleNamespace(
        skills=["Python", "FastAPI"],
        experience=[{"description": "Built database APIs"}],
        projects=[], education=[], certifications=[], languages=[],
    )

    mock_llm_evaluator = AsyncMock()
    mock_llm_evaluator.evaluate.return_value = []

    service = HybridMatchingService(evaluator=mock_llm_evaluator)
    enriched, verdicts = pytest.importorskip("asyncio").run(service.match(job, resume, extracted, config=None))

    # LLM should not be called because Jest has 0 keyword/stem overlap with FastAPI/Python/database APIs
    assert not mock_llm_evaluator.evaluate.called
    skill_verdict = next((v for v in verdicts if v.requirement_id == "skill:1"), None)
    assert skill_verdict is not None
    assert skill_verdict.status == MatchStatus.NO_MATCH


def test_scenario_e_weak_evidence_returns_unresolved_or_unmet():
    """Scenario E: Related but weak evidence -> LLM returns UNRESOLVED -> does not count as match."""
    job = SimpleNamespace(required_skills=["authorization"], skills=["authorization"])
    resume = SimpleNamespace(
        skills=["JWT Authentication"],
        experience=[{"description": "Implemented JWT authentication token signing."}],
        projects=[], education=[], certifications=[], languages=[],
    )
    extracted = SimpleNamespace(
        skills=["JWT Authentication"],
        experience=[{"description": "Implemented JWT authentication token signing."}],
        projects=[], education=[], certifications=[], languages=[],
    )

    mock_llm_evaluator = AsyncMock()
    mock_llm_evaluator.evaluate.return_value = [
        MatchVerdict(
            requirement_id="skill:1",
            status=MatchStatus.UNRESOLVED,
            confidence=0.50,
            evidence_ids=["experience:1"],
            reasoning="Evidence demonstrates authentication, but authorization roles are not established.",
            method=MatchMethod.LLM_UNRESOLVED,
        )
    ]

    service = HybridMatchingService(evaluator=mock_llm_evaluator)
    enriched, verdicts = pytest.importorskip("asyncio").run(service.match(job, resume, extracted, config=None))

    skill_verdict = next((v for v in verdicts if v.requirement_id == "skill:1"), None)
    assert skill_verdict is not None
    assert skill_verdict.status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_required_skill_denominator_and_scoring_invariance():
    """Verify that semantic fallback matches increment matched skills without altering the denominator or 30% weight."""
    service = ComponentScoringService()
    job = SimpleNamespace(
        required_skills=["React", "Node.js", "query optimization", "state management"],
        skills=["React", "Node.js", "query optimization", "state management"],
    )
    resume = SimpleNamespace(
        skills=["React", "Node.js"],
        experience=[{"description": "Optimized queries"}],
        projects=[], education=[], certifications=[], languages=[],
    )

    # Deterministic match gets 2/4 (React, Node.js)
    # LLM confirms query optimization
    match_verdicts = [
        MatchVerdict(
            requirement_id="skill:3",
            status=MatchStatus.MATCHED,
            confidence=0.90,
            evidence_ids=["experience:1"],
            reasoning="Candidate query optimization demonstrated in experience.",
            method=MatchMethod.LLM_CONFIRMED,
        )
    ]

    scores = service.score(resume, job, config=None, match_verdicts=match_verdicts)
    # Total required = 4, Matched = 3 (React, Node.js, query optimization) -> 75%
    assert len(scores.skills.matched_items) == 3
    assert len(scores.skills.missing_items) == 1
    assert scores.skills.score == 75.0

    # Verify 30% weight in WeightCalculationService
    app_cats = WeightCalculationService.applicable_categories(job)
    final_score = WeightCalculationService.final_score(0, 0, 0, components=scores, applicable_categories=app_cats)
    # Only skills required -> (75 * 0.30) / 30 * 100 = 75.0
    assert final_score == 75.0
