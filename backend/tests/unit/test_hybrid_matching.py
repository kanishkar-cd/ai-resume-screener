import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.schemas.matching import (
    Evidence, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict,
    Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, GroqMatchEvaluator,
    HybridMatchingService, RequirementBuilder,
)
from app.services.scoring.component_scoring_service import ComponentScoringService


def settings(**values):
    return Settings(
        ENABLE_HYBRID_MATCHING=True, GROQ_API_KEY="test-key",
        HYBRID_MATCHING_LLM_CONFIDENCE_THRESHOLD=0.8,
        HYBRID_MATCHING_KEYWORD_OVERLAP_THRESHOLD=0.1,
        **values,
    )


def test_contracts_require_a_method_for_matched_verdicts() -> None:
    with pytest.raises(ValidationError):
        MatchVerdict(requirement_id="skill:1", status="MATCHED", confidence=1)
    verdict = MatchVerdict(
        requirement_id="skill:1", status="MATCHED", confidence=1,
        method="alias",
    )
    assert verdict.method == MatchMethod.ALIAS


def test_requirement_builder_preserves_contextual_boundary() -> None:
    job = SimpleNamespace(
        skills=["Python"], preferred_skills=[], degree_requirements=["Bachelor's Degree"],
        keywords=["Docker"], responsibilities=["Build reliable APIs"],
        experience_requirements=[{"display_value": "3 years"}],
    )
    config = SimpleNamespace(
        mandatory_skills=["Python"], required_certifications=["PMP"], required_languages=["English"],
    )
    requirements = RequirementBuilder.build(job, config)
    kinds = {item.kind for item in requirements}
    assert RequirementKind.SKILL in kinds
    assert RequirementKind.RESPONSIBILITY in kinds
    assert RequirementKind.PROJECT_RELEVANCE not in kinds
    assert RequirementKind.CONTEXTUAL_EXPERIENCE not in kinds


def test_deterministic_alias_taxonomy_and_absence() -> None:
    matcher = DeterministicRequirementMatcher()
    resume = SimpleNamespace(
        skills=["nodejs"], education=[{"degree": "Master of Science"}],
        certifications=[], languages=[],
    )
    alias = matcher.match(Requirement(
        requirement_id="skill:1", kind="skill", text="Node.js", canonical_value="Node.js",
    ), resume, [])
    taxonomy = matcher.match(Requirement(
        requirement_id="degree:1", kind="degree", text="Bachelor's Degree",
    ), resume, [])
    absent = matcher.match(Requirement(
        requirement_id="skill:2", kind="skill", text="Rust",
    ), resume, [])
    assert alias.status == MatchStatus.MATCHED and alias.method == MatchMethod.ALIAS
    assert taxonomy.status == MatchStatus.MATCHED and taxonomy.method == MatchMethod.TAXONOMY
    assert absent.status == MatchStatus.NO_MATCH


def test_only_contextual_evidence_is_unresolved() -> None:
    matcher = DeterministicRequirementMatcher()
    requirement = Requirement(
        requirement_id="responsibility:1", kind="responsibility",
        text="Build reliable APIs",
    )
    verdict = matcher.match(requirement, SimpleNamespace(), [])
    assert verdict.status == MatchStatus.UNRESOLVED


def test_evidence_builder_excludes_identity_and_contact_data() -> None:
    extracted = SimpleNamespace(
        candidate_name="Private Name", email="private@example.com",
        projects=[{"name": "Platform", "description": "Built Docker services", "technologies": ["Docker"]}],
        experience=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    serialized = json.dumps([item.model_dump() for item in evidence])
    assert "Private Name" not in serialized and "private@example.com" not in serialized


def test_collapsed_affinda_project_descriptions_keep_independent_provenance() -> None:
    extracted = SimpleNamespace(
        projects=[
            {"name": "SustainTrack.me", "description": "Sustainability platform\nFull-stack home service booking application\nPhishing detection application\nGroundwater monitoring application", "technologies": []},
            {"name": "KeeHome", "description": None, "technologies": []},
            {"name": "PhisScan", "description": None, "technologies": []},
            {"name": "Aquanta", "description": None, "technologies": []},
        ], experience=[],
    )
    evidence = EvidenceBuilder.build(extracted)
    assert [item.evidence_id for item in evidence] == ["project:1", "project:2", "project:3", "project:4"]
    assert "KeeHome" in evidence[1].text
    assert "Full-stack home service" in evidence[1].text
    assert evidence[1].canonical_terms == []


def test_groq_payload_uses_model_compatible_json_object_mode() -> None:
    evaluator = GroqMatchEvaluator(settings())
    payload = evaluator._payload(
        [Requirement(requirement_id="responsibility:1", kind="responsibility", text="Build web applications")],
        [Evidence(evidence_id="project:1", kind="project", text="Built a web application")],
    )
    assert payload["response_format"] == {"type": "json_object"}
    assert "json_schema" not in json.dumps(payload["response_format"])


def test_llm_evidence_and_confidence_validation() -> None:
    evaluator = GroqMatchEvaluator(settings())
    requirement = Requirement(requirement_id="project_relevance:1", kind="project_relevance", text="Docker")
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Docker platform")]
    invalid = evaluator._validate(LLMVerdictBatch(verdicts=[{
        "requirement_id": requirement.requirement_id, "status": "MATCHED",
        "confidence": 0.99, "evidence_ids": ["project:999"], "reasoning": "Relevant",
    }]), [requirement], evidence, {requirement.requirement_id: {"project:1"}})
    low = evaluator._validate(LLMVerdictBatch(verdicts=[{
        "requirement_id": requirement.requirement_id, "status": "MATCHED",
        "confidence": 0.79, "evidence_ids": ["project:1"], "reasoning": "Relevant",
    }]), [requirement], evidence, {requirement.requirement_id: {"project:1"}})
    assert invalid[0].status == MatchStatus.UNRESOLVED and not invalid[0].evidence_ids
    assert low[0].status == MatchStatus.UNRESOLVED


@pytest.mark.asyncio
async def test_malformed_llm_output_retries_once_then_falls_back(monkeypatch) -> None:
    calls = 0

    async def post(*args, **kwargs):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}, request=httpx.Request("POST", "https://example.test"))

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    evaluator = GroqMatchEvaluator(settings())
    result = await evaluator.evaluate(
        [Requirement(requirement_id="project_relevance:1", kind="project_relevance", text="Docker")],
        [Evidence(evidence_id="project:1", kind="project", text="Docker platform")],
    )
    assert result == [] and calls == 2


@pytest.mark.asyncio
async def test_evaluator_cache_avoids_second_call(monkeypatch) -> None:
    GroqMatchEvaluator._cache.clear()
    calls = 0

    async def post(*args, **kwargs):
        nonlocal calls
        calls += 1
        content = json.dumps({"verdicts": [{
            "requirement_id": "project_relevance:1", "status": "MATCHED",
            "confidence": 0.95, "evidence_ids": ["project:1"], "reasoning": "Direct evidence",
        }]})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]}, request=httpx.Request("POST", "https://example.test"))

    monkeypatch.setattr(httpx.AsyncClient, "post", post)
    evaluator = GroqMatchEvaluator(settings())
    requirements = [Requirement(requirement_id="project_relevance:1", kind="project_relevance", text="Docker")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Docker platform")]
    first = await evaluator.evaluate(requirements, evidence)
    second = await evaluator.evaluate(requirements, evidence)
    assert first == second and calls == 1


@pytest.mark.asyncio
async def test_validated_llm_match_enriches_scoring_copy_only() -> None:
    class Evaluator:
        async def evaluate(self, requirements, evidence, allowed_evidence=None):
            target = next(item for item in requirements if item.kind == RequirementKind.RESPONSIBILITY)
            return [MatchVerdict(
                requirement_id=target.requirement_id, status="MATCHED", confidence=.9,
                evidence_ids=["project:1"], reasoning="Relevant", method="llm_confirmed",
            )]

    service = HybridMatchingService(settings=settings(), evaluator=Evaluator())
    job = SimpleNamespace(
        skills=[], preferred_skills=[], degree_requirements=[], keywords=["Docker"],
        responsibilities=["Deploy containerized applications"], experience_requirements=[],
    )
    resume = SimpleNamespace(skills=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(
        projects=[{"name": "Platform", "description": "Deploy containerized applications with Docker", "technologies": []}],
        experience=[],
    )
    enriched, verdicts = await service.match(job, resume, extracted, SimpleNamespace(
        mandatory_skills=[], required_certifications=[], required_languages=[],
    ))
    assert enriched.projects[0]["technologies"] == []
    assert extracted.projects[0]["technologies"] == []
    assert any(item.method == MatchMethod.LLM_CONFIRMED for item in verdicts)

    config = SimpleNamespace(
        mandatory_skills=[], min_experience_years=0, required_degree=None,
        required_certifications=[], required_languages=[],
    )
    scoring_resume = SimpleNamespace(
        skills=[], experience=[], education=[], certifications=[], languages=[],
    )
    before = ComponentScoringService().score(scoring_resume, job, config, extracted.projects)
    after = ComponentScoringService().score(scoring_resume, job, config, enriched.projects)
    assert before.projects.score == after.projects.score == 0
    assert before.skills == after.skills
    assert before.experience == after.experience
    assert before.education == after.education


def test_ai_verdict_classification_contract_validation() -> None:
    verdict_confirmed = MatchVerdict(
        requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9,
        evidence_ids=["project:1"], method=MatchMethod.LLM_CONFIRMED,
    )
    assert verdict_confirmed.method == MatchMethod.LLM_CONFIRMED

    verdict_rejected = MatchVerdict(
        requirement_id="responsibility:2", status=MatchStatus.NO_MATCH, confidence=0.95,
        evidence_ids=["project:1"], reasoning="Candidate text does not satisfy database requirement.",
        method=MatchMethod.LLM_REJECTED,
    )
    assert verdict_rejected.method == MatchMethod.LLM_REJECTED

    verdict_unresolved = MatchVerdict(
        requirement_id="responsibility:3", status=MatchStatus.UNRESOLVED, confidence=0.0,
        evidence_ids=[], reasoning="Ambiguous context.",
        method=MatchMethod.LLM_UNRESOLVED,
    )
    assert verdict_unresolved.method == MatchMethod.LLM_UNRESOLVED


@pytest.mark.asyncio
async def test_multi_candidate_isolation_and_evidence_prefilter_fallback() -> None:
    class MockGroqEvaluator:
        enabled = True
        async def evaluate(self, requirements, evidence, allowed_evidence=None):
            verdicts = []
            for r in requirements:
                if "database" in r.text.casefold():
                    verdicts.append(MatchVerdict(
                        requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.9,
                        evidence_ids=[e.evidence_id for e in evidence[:1]], reasoning="AI confirmed database match.",
                        method=MatchMethod.LLM_CONFIRMED,
                    ))
                else:
                    verdicts.append(MatchVerdict(
                        requirement_id=r.requirement_id, status=MatchStatus.NO_MATCH, confidence=0.85,
                        evidence_ids=[e.evidence_id for e in evidence[:1]], reasoning="AI rejected requirement.",
                        method=MatchMethod.LLM_REJECTED,
                    ))
            return verdicts

    service = HybridMatchingService(settings=settings(), evaluator=MockGroqEvaluator())
    job = SimpleNamespace(
        skills=[], preferred_skills=[], degree_requirements=[], keywords=[],
        responsibilities=["Architect database schemas", "Manage Kubernetes clusters"],
        experience_requirements=[],
    )

    # Candidate 1
    extracted_cand1 = SimpleNamespace(
        projects=[{"name": "App 1", "description": "Built PostgreSQL database models", "technologies": ["PostgreSQL"]}],
        experience=[],
    )
    _, verdicts_cand1 = await service.match(job, SimpleNamespace(skills=[], education=[], certifications=[], languages=[]), extracted_cand1, SimpleNamespace(mandatory_skills=[], required_certifications=[], required_languages=[]))

    # Candidate 2
    extracted_cand2 = SimpleNamespace(
        projects=[{"name": "App 2", "description": "Designed UI components in React", "technologies": ["React"]}],
        experience=[],
    )
    _, verdicts_cand2 = await service.match(job, SimpleNamespace(skills=[], education=[], certifications=[], languages=[]), extracted_cand2, SimpleNamespace(mandatory_skills=[], required_certifications=[], required_languages=[]))

    # Assert candidate 1 verdicts
    resp1_cand1 = next(v for v in verdicts_cand1 if v.requirement_id == "responsibility:1")
    assert resp1_cand1.method == MatchMethod.LLM_CONFIRMED
    assert resp1_cand1.status == MatchStatus.MATCHED

    # Assert candidate 2 verdicts
    resp1_cand2 = next(v for v in verdicts_cand2 if v.requirement_id == "responsibility:1")
    assert resp1_cand2.method == MatchMethod.LLM_CONFIRMED

    resp2_cand2 = next(v for v in verdicts_cand2 if v.requirement_id == "responsibility:2")
    assert resp2_cand2.method == MatchMethod.LLM_REJECTED
    assert resp2_cand2.status == MatchStatus.NO_MATCH

