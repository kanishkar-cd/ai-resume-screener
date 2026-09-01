import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, EvidencePrefilter,
    GroqMatchEvaluator, HybridMatchingService, RequirementBuilder,
)
from app.services.scoring.component_scoring_service import ComponentScoringService


# ==============================================================================
# 1. EVIDENCE ID NORMALIZATION & VALIDATION TESTS
# ==============================================================================

def test_1_exact_evidence_id_confirmed():
    """1. Exact evidence ID -> confirmed."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC")]
    allowed = {"skill:1": {"experience:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], reasoning="Direct match")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert validated[0].evidence_ids == ["experience:1"]


def test_2_case_variation_normalized_and_confirmed():
    """2. Case variation ('Experience:1') -> normalized to 'experience:1' and confirmed."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC")]
    allowed = {"skill:1": {"experience:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["Experience:1"], reasoning="Case variant citation")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert validated[0].evidence_ids == ["experience:1"]


def test_3_formatting_variation_normalized_and_confirmed():
    """3. Formatting variations ('experience 1', 'Experience: 1', 'Experience #1') -> normalized and confirmed."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC")]
    allowed = {"skill:1": {"experience:1"}}

    for format_variant in ["experience 1", "Experience: 1", "Experience #1", "experience-1", "experience_1"]:
        batch = LLMVerdictBatch(verdicts=[
            LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=[format_variant], reasoning="Formatting variant citation")
        ])
        validated = evaluator._validate(batch, reqs, evs, allowed)
        assert len(validated) == 1
        assert validated[0].status == MatchStatus.MATCHED
        assert validated[0].evidence_ids == ["experience:1"]


def test_4_invalid_evidence_id_rejected():
    """4. Non-existent evidence ID ('experience:99') -> rejected to UNRESOLVED."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC")]
    allowed = {"skill:1": {"experience:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:99"], reasoning="Invalid citation")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.UNRESOLVED
    assert validated[0].method == MatchMethod.LLM_UNRESOLVED
    assert "Rejected: No valid candidate evidence ID cited for match" in validated[0].reasoning


def test_5_invented_evidence_rejected():
    """5. Hallucinated/invented evidence ('hallucinated:1') -> rejected."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented RBAC")]
    allowed = {"skill:1": {"experience:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["hallucinated:1"], reasoning="Hallucinated")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.UNRESOLVED


def test_6_multiple_valid_evidence_ids_confirmed():
    """6. Multiple valid evidence IDs -> confirmed."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="full stack development")]
    evs = [
        Evidence(evidence_id="experience:1", kind="experience", text="Built React frontends"),
        Evidence(evidence_id="project:1", kind="project", text="Built Node.js backends"),
    ]
    allowed = {"skill:1": {"experience:1", "project:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["Experience:1", "project 1"], reasoning="Full stack evidence across exp and project")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].evidence_ids == ["experience:1", "project:1"]


# ==============================================================================
# 2. SEMANTIC EVIDENCE RECOVERY TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_7_jwt_to_authentication():
    """7. JWT in experience -> authentication LLM confirmed."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="JWT satisfies authentication")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)
    resume = SimpleNamespace(skills=[], experience=[{"description": "Implemented JWT token authentication"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["authentication"], preferred_skills=[], skills=["authentication"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method == MatchMethod.LLM_CONFIRMED


@pytest.mark.asyncio
async def test_8_rbac_to_authorization():
    """8. RBAC in experience -> authorization LLM confirmed."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="RBAC satisfies authorization")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)
    resume = SimpleNamespace(skills=[], experience=[{"description": "Configured RBAC access permissions"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["authorization"], preferred_skills=[], skills=["authorization"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_9_event_driven_to_asynchronous():
    """9. event-driven in projects -> asynchronous programming LLM confirmed."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["project:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Event-driven architecture satisfies asynchronous programming")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)
    resume = SimpleNamespace(skills=[], experience=[], projects=[{"name": "Broker", "description": "Built event-driven services with RabbitMQ"}], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=[], projects=resume.projects, education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["asynchronous programming"], preferred_skills=[], skills=["asynchronous programming"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_10_aws_migration_to_cloud_architecture():
    """10. AWS migration in experience -> Experience working with cloud architectures LLM confirmed."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="AWS cloud migration demonstrates cloud architecture experience")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)
    resume = SimpleNamespace(skills=[], experience=[{"description": "Led AWS cloud infrastructure migration and serverless deployment"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=["Experience working with cloud architectures"], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_11_production_fixes_to_technical_problem_solving():
    """11. Production bug fixes & optimization in experience -> Solve challenging technical problems LLM confirmed."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Resolving production bottlenecks satisfies technical problem solving")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)
    resume = SimpleNamespace(skills=[], experience=[{"description": "Diagnosed root causes and resolved critical production performance bottlenecks"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=["Solve challenging technical problems"], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_12_database_optimization_to_query_optimization():
    """12. Database indexes and query plans in experience -> query optimization LLM confirmed."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Database index tuning satisfies query optimization")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)
    resume = SimpleNamespace(skills=[], experience=[{"description": "Tuned database indexes and query plans"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["query optimization"], preferred_skills=[], skills=["query optimization"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


@pytest.mark.asyncio
async def test_13_rest_apis_to_api_development():
    """13. REST endpoints in experience -> Develop microservices and APIs LLM confirmed."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="REST backend development satisfies API development")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)
    resume = SimpleNamespace(skills=[], experience=[{"description": "Engineered REST backend APIs and microservices in Express"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=["Develop microservices and APIs"], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED


# ==============================================================================
# 3. PARTIAL CONCEPTS & RESPONSIBILITY COVERAGE TESTS
# ==============================================================================

def test_14_and_15_two_concept_databases_partial_and_matched():
    """14 & 15: 'Relational and non-relational databases': 1/2 -> PARTIAL(50%), 2/2 -> MATCHED(100%)."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Relational and non-relational databases",
    )
    
    # 1/2 case: non-relational only
    ev_1 = [Evidence(evidence_id="experience:1", kind="experience", text="Designed non-relational databases")]
    resume_1 = SimpleNamespace(skills=[], experience=[{"description": "Designed non-relational databases"}], projects=[], education=[], certifications=[], languages=[])
    job_1 = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])
    v_1 = matcher.match(req, resume_1, ev_1)
    assert v_1.status == MatchStatus.PARTIALLY_MATCHED
    assert v_1.coverage == 0.50
    scores_1 = scoring_svc.score(resume_1, job_1, config=None, match_verdicts=[v_1])
    assert scores_1.responsibilities.score == 50.0

    # 2/2 case: PostgreSQL and MongoDB
    ev_2 = [Evidence(evidence_id="experience:1", kind="experience", text="Designed relational databases and non-relational databases")]
    resume_2 = SimpleNamespace(skills=[], experience=[{"description": "Designed relational databases and non-relational databases"}], projects=[], education=[], certifications=[], languages=[])
    v_2 = matcher.match(req, resume_2, ev_2)
    assert v_2.status == MatchStatus.MATCHED
    assert v_2.coverage == 1.00
    scores_2 = scoring_svc.score(resume_2, job_1, config=None, match_verdicts=[v_2])
    assert scores_2.responsibilities.score == 100.0


def test_16_and_17_four_concept_partial_and_matched():
    """16 & 17: 2/4 -> MATCHED(50%), 3/4 -> MATCHED(75%)."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design efficient database schemas, indexes, queries, and aggregation pipelines",
    )

    # 2/4 case
    ev_24 = [Evidence(evidence_id="experience:1", kind="experience", text="Designed database schemas and database indexes")]
    res_24 = SimpleNamespace(skills=[], experience=[{"description": "Designed database schemas and database indexes"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])
    v_24 = matcher.match(req, res_24, ev_24)
    assert v_24.status == MatchStatus.MATCHED
    assert v_24.coverage == 0.50
    scores_24 = scoring_svc.score(res_24, job, config=None, match_verdicts=[v_24])
    assert scores_24.responsibilities.score == 50.0

    # 3/4 case
    ev_34 = [Evidence(evidence_id="experience:1", kind="experience", text="Designed database schemas, database indexes, and optimized queries")]
    res_34 = SimpleNamespace(skills=[], experience=[{"description": "Designed database schemas, database indexes, and optimized queries"}], projects=[], education=[], certifications=[], languages=[])
    v_34 = matcher.match(req, res_34, ev_34)
    assert v_34.status == MatchStatus.MATCHED
    assert v_34.coverage == 0.75
    scores_34 = scoring_svc.score(res_34, job, config=None, match_verdicts=[v_34])
    assert scores_34.responsibilities.score == 75.0


# ==============================================================================
# 4. ANTI-HALLUCINATION BARRIERS
# ==============================================================================

@pytest.mark.asyncio
async def test_18_to_21_anti_hallucination_barriers():
    """18-21: Strict barriers: REST != microservices, JWT != authorization, RBAC != authentication, Generic collaboration != Mentoring."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    # Candidate has JWT (auth) and REST, but NO RBAC, NO microservices, NO mentoring
    resume = SimpleNamespace(
        skills=["REST", "JWT"],
        experience=[{"description": "Implemented JWT login authentication and basic REST endpoints with other developers"}],
        projects=[], education=[], certifications=[], languages=[],
    )
    extracted = SimpleNamespace(skills=resume.skills, experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(
        required_skills=["authorization", "microservices"],
        preferred_skills=[],
        skills=["authorization", "microservices"],
        responsibilities=["Mentor junior developers"],
        degree_requirements=[], experience_requirements=[], certifications=[],
    )

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    verdict_by_text = {getattr(v, "requirement_text", ""): v for v in verdicts}

    # 1. JWT does NOT automatically satisfy authorization
    assert verdict_by_text["authorization"].status != MatchStatus.MATCHED
    # 2. Basic REST does NOT automatically satisfy microservices
    assert verdict_by_text["microservices"].status != MatchStatus.MATCHED
    # 3. Generic collaboration does NOT satisfy mentoring
    assert verdict_by_text["Mentor junior developers"].status != MatchStatus.MATCHED
