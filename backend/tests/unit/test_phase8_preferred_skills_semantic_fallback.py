import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, HybridMatchingService, RequirementBuilder,
)
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import COMPONENT_WEIGHTS, WeightCalculationService


def test_scenario_1_preferred_skill_deterministic_match():
    """Test 1: Preferred skill deterministic match -> matched without LLM."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(requirement_id="skill:2", kind=RequirementKind.SKILL, text="Docker", required=False)
    resume = SimpleNamespace(skills=["Docker"], experience=[], education=[], certifications=[], languages=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Docker", canonical_terms=["Docker"])]

    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_scenario_2_preferred_skill_project_evidence_llm_match():
    """Test 2: Preferred skill deterministic miss + project evidence -> LLM called -> MATCHED."""
    job = SimpleNamespace(
        required_skills=["React"],
        preferred_skills=["GraphQL"],
        skills=["React", "GraphQL"],
    )
    resume = SimpleNamespace(
        skills=["React"],
        experience=[],
        projects=[{
            "name": "Customer Portal",
            "description": "Developed a GraphQL query federation and mutation pipeline.",
            "technologies": ["React", "GraphQL"],
        }],
        education=[], certifications=[], languages=[],
    )
    extracted = SimpleNamespace(
        skills=["React"],
        experience=[],
        projects=[{
            "name": "Customer Portal",
            "description": "Developed a GraphQL query federation and mutation pipeline.",
            "technologies": ["React", "GraphQL"],
        }],
        education=[], certifications=[], languages=[],
    )

    mock_llm = AsyncMock()
    mock_llm.evaluate.return_value = [
        MatchVerdict(
            requirement_id="skill:2",
            status=MatchStatus.MATCHED,
            confidence=0.92,
            evidence_ids=["project:1"],
            reasoning="Candidate built GraphQL pipeline in project.",
            method=MatchMethod.LLM_CONFIRMED,
        )
    ]

    service = HybridMatchingService(evaluator=mock_llm)
    enriched, verdicts = pytest.importorskip("asyncio").run(service.match(job, resume, extracted, config=None))

    pref_verdict = next((v for v in verdicts if v.requirement_id == "skill:2"), None)
    assert pref_verdict is not None
    assert pref_verdict.status == MatchStatus.MATCHED


def test_scenario_3_preferred_skill_experience_evidence_llm_match():
    """Test 3: Preferred skill deterministic miss + experience evidence -> LLM called -> MATCHED."""
    job = SimpleNamespace(
        required_skills=["React"],
        preferred_skills=["cloud orchestration"],
        skills=["React", "cloud orchestration"],
    )
    resume = SimpleNamespace(
        skills=["React"],
        experience=[{
            "title": "Full Stack Dev",
            "company": "CloudTech",
            "description": "Orchestrated container clusters across high-availability AWS nodes.",
            "technologies": ["Docker"],
        }],
        projects=[], education=[], certifications=[], languages=[],
    )
    extracted = SimpleNamespace(
        skills=["React"],
        experience=[{
            "title": "Full Stack Dev",
            "company": "CloudTech",
            "description": "Orchestrated container clusters across high-availability AWS nodes.",
            "technologies": ["Docker"],
        }],
        projects=[], education=[], certifications=[], languages=[],
    )

    mock_llm = AsyncMock()
    mock_llm.evaluate.return_value = [
        MatchVerdict(
            requirement_id="skill:2",
            status=MatchStatus.MATCHED,
            confidence=0.90,
            evidence_ids=["experience:1"],
            reasoning="Candidate managed cloud orchestration in experience.",
            method=MatchMethod.LLM_CONFIRMED,
        )
    ]

    service = HybridMatchingService(evaluator=mock_llm)
    enriched, verdicts = pytest.importorskip("asyncio").run(service.match(job, resume, extracted, config=None))

    assert mock_llm.evaluate.called
    pref_verdict = next((v for v in verdicts if v.requirement_id == "skill:2"), None)
    assert pref_verdict is not None
    assert pref_verdict.status == MatchStatus.MATCHED


def test_scenario_4_preferred_skill_no_evidence_does_not_call_llm():
    """Test 4: Preferred skill deterministic miss + zero evidence -> LLM NOT CALLED -> UNMET."""
    job = SimpleNamespace(
        required_skills=["Python"],
        preferred_skills=["Terraform"],
        skills=["Python", "Terraform"],
    )
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

    mock_llm = AsyncMock()
    mock_llm.evaluate.return_value = []

    service = HybridMatchingService(evaluator=mock_llm)
    enriched, verdicts = pytest.importorskip("asyncio").run(service.match(job, resume, extracted, config=None))

    assert not mock_llm.evaluate.called
    pref_verdict = next((v for v in verdicts if v.requirement_id == "skill:2"), None)
    assert pref_verdict is not None
    assert pref_verdict.status == MatchStatus.NO_MATCH


def test_scenario_5_preferred_skill_unresolved_is_unmet():
    """Test 5: Preferred skill LLM UNRESOLVED -> does not count towards score."""
    scoring_svc = ComponentScoringService()
    job = SimpleNamespace(
        required_skills=["React"],
        preferred_skills=["AWS"],
        skills=["React", "AWS"],
    )
    resume = SimpleNamespace(
        skills=["React"],
        experience=[{"description": "Worked with cloud technologies"}],
        projects=[], education=[], certifications=[], languages=[],
    )

    verdicts = [
        MatchVerdict(
            requirement_id="skill:2",
            status=MatchStatus.UNRESOLVED,
            confidence=0.45,
            evidence_ids=["experience:1"],
            reasoning="Cloud technologies mentioned without specific AWS evidence.",
            method=MatchMethod.LLM_UNRESOLVED,
        )
    ]

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=verdicts)
    assert "AWS" in scores.preferred_skills.missing_items
    assert scores.preferred_skills.score == 0.0


def test_scenario_6_preferred_skill_deduplication_counted_once():
    """Test 6: Same preferred skill in skills + experience + project -> counted once."""
    scoring_svc = ComponentScoringService()
    job = SimpleNamespace(
        required_skills=["Python"],
        preferred_skills=["Docker"],
        skills=["Python", "Docker"],
    )
    resume = SimpleNamespace(
        skills=["Python", "Docker"],
        experience=[{"description": "Dockerized microservices", "technologies": ["Docker"]}],
        projects=[{"name": "App", "technologies": ["Docker"]}],
        education=[], certifications=[], languages=[],
    )

    scores = scoring_svc.score(resume, job, config=None, projects=resume.projects)
    assert len(scores.preferred_skills.matched_items) == 1
    assert scores.preferred_skills.score == 100.0


def test_scenario_7_and_8_preferred_skills_component_separation_and_15_percent_weight():
    """Test 7 & 8: Preferred Skills do not alter Required Skills score, and contribute strictly to 15% weight."""
    scoring_svc = ComponentScoringService()
    job = SimpleNamespace(
        required_skills=["React", "Node.js"],
        preferred_skills=["AWS", "Docker", "GraphQL", "Kubernetes"],
        skills=["React", "Node.js", "AWS", "Docker", "GraphQL", "Kubernetes"],
    )
    resume = SimpleNamespace(
        skills=["React"],  # 1/2 required skills
        experience=[{"description": "Deployed on AWS"}],  # Will get AWS via LLM
        projects=[], education=[], certifications=[], languages=[],
    )

    # 1 deterministic match for AWS, 1 for Docker via LLM
    match_verdicts = [
        MatchVerdict(
            requirement_id="skill:3",  # AWS (preferred skill)
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["experience:1"],
            reasoning="AWS cloud deployments demonstrated.",
            method=MatchMethod.LLM_CONFIRMED,
        ),
        MatchVerdict(
            requirement_id="skill:4",  # Docker (preferred skill)
            status=MatchStatus.MATCHED,
            confidence=0.90,
            evidence_ids=["experience:1"],
            reasoning="Docker containerization demonstrated.",
            method=MatchMethod.LLM_CONFIRMED,
        ),
    ]

    scores = scoring_svc.score(resume, job, config=None, match_verdicts=match_verdicts)

    # Required Skills: 1 / 2 = 50%
    assert scores.skills.score == 50.0
    assert len(scores.skills.matched_items) == 1
    assert len(scores.skills.missing_items) == 1

    # Preferred Skills: 2 / 4 = 50%
    assert scores.preferred_skills.score == 50.0
    assert len(scores.preferred_skills.matched_items) == 2
    assert len(scores.preferred_skills.missing_items) == 2

    # Verify weighting in WeightCalculationService
    app_cats = WeightCalculationService.applicable_categories(job)
    weighted, raw_total, weighted_total, effective_weights = WeightCalculationService.calculate(
        scores, config=None, applicable_categories=app_cats
    )

    # Total applicable weight = 45 + 15 = 60%
    # Effective weight skills = 45 / 60 * 100 = 75.0% -> weighted.skills = 50% * 75.0 = 37.5
    # Effective weight pref = 15 / 60 * 100 = 25.0% -> weighted.preferred_skills = 50% * 25.0 = 12.5
    # Normalized score = (37.5 + 12.5) = 50.0 / 100
    assert round(weighted.skills, 2) == 37.5
    assert round(weighted.preferred_skills, 2) == 12.5
    assert weighted_total == 50.0
    final = WeightCalculationService.final_score(0, 0, 0, components=scores, applicable_categories=app_cats)
    assert final == 50.0
