import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    EvidenceBuilder, EvidencePrefilter, GroqMatchEvaluator, HybridMatchingService, RequirementBuilder,
)


def test_evidence_prefilter_semantic_synonym_selection():
    """Verify EvidencePrefilter captures semantic synonyms (RBAC, async/await, mobile-first, GitHub Actions)."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)

    # 1. Authorization requirement with RBAC evidence
    auth_req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")
    auth_ev = [
        Evidence(evidence_id="experience:1", kind="experience", text="Implemented role-based access control and JWT permissions"),
        Evidence(evidence_id="education:1", kind="education", text="B.Tech Computer Science"),
    ]
    selected_auth = prefilter.select(auth_req, auth_ev)
    assert any(e.evidence_id == "experience:1" for e in selected_auth)

    # 2. Asynchronous programming with async/await evidence
    async_req = Requirement(requirement_id="skill:2", kind=RequirementKind.REQUIRED_SKILL, text="asynchronous programming")
    async_ev = [
        Evidence(evidence_id="experience:1", kind="experience", text="Built async/await non-blocking API microservices"),
    ]
    selected_async = prefilter.select(async_req, async_ev)
    assert any(e.evidence_id == "experience:1" for e in selected_async)

    # 3. Responsive design with mobile-first UI evidence
    resp_req = Requirement(requirement_id="skill:3", kind=RequirementKind.REQUIRED_SKILL, text="responsive design")
    resp_ev = [
        Evidence(evidence_id="summary:1", kind="summary", text="Expert in building mobile-first responsive web applications using CSS grid"),
    ]
    selected_resp = prefilter.select(resp_req, resp_ev)
    assert any(e.evidence_id == "summary:1" for e in selected_resp)

    # 4. CI/CD with GitHub Actions evidence
    cicd_req = Requirement(requirement_id="skill:4", kind=RequirementKind.REQUIRED_SKILL, text="CI/CD")
    cicd_ev = [
        Evidence(evidence_id="project:1", kind="project", text="Configured GitHub Actions automated deployment pipelines"),
    ]
    selected_cicd = prefilter.select(cicd_req, cicd_ev)
    assert any(e.evidence_id == "project:1" for e in selected_cicd)

    # 5. Absent skill (Docker) with zero evidence returns empty
    docker_req = Requirement(requirement_id="skill:5", kind=RequirementKind.REQUIRED_SKILL, text="Docker")
    selected_docker = prefilter.select(docker_req, auth_ev)
    assert len(selected_docker) == 0


@pytest.mark.asyncio
async def test_llm_fallback_semantic_positive_and_negative_cases():
    """Verify end-to-end HybridMatchingService resolves semantic equivalents and rejects unsupported technologies."""
    # Setup candidate with real semantic evidence (JWT auth, RBAC, mobile-first, async/await, MongoDB schemas, query tuning, GitHub Actions)
    resume = SimpleNamespace(
        skills=["JavaScript", "React", "Node.js", "Express", "MongoDB"],
        certifications=[],
        education=[{"degree": "Bachelor of Technology", "institution": "Anna University"}],
        languages=["English"],
        experience=[
            {
                "designation": "Software Developer Intern",
                "company": "Tech Corp",
                "description": "Implemented role-based access control (RBAC) and JWT token authentication. Built async/await non-blocking endpoints.",
            },
            {
                "designation": "Junior Developer",
                "company": "Web Solutions",
                "description": "Designed MongoDB schemas, optimized database queries with indexes, and configured GitHub Actions CI/CD pipelines.",
            },
        ],
        projects=[
            {
                "name": "E-Commerce App",
                "description": "Built responsive mobile-first UI with React. Implemented full order management lifecycle.",
                "technologies": ["React", "Node.js", "MongoDB"],
            }
        ],
    )
    extracted = SimpleNamespace(
        candidate_name="Aditi Sharma",
        summary="Motivated developer with experience building responsive web applications.",
        skills=resume.skills,
        education=resume.education,
        experience=resume.experience,
        projects=resume.projects,
        certifications=[],
        languages=resume.languages,
    )
    job = SimpleNamespace(
        required_skills=[
            "authentication",
            "authorization",
            "responsive design",
            "asynchronous programming",
            "schema design",
            "query optimization",
            "CI/CD",
            "Docker",
            "AWS",
            "Redis",
            "GraphQL",
            "Next.js",
        ],
        preferred_skills=[],
        skills=[
            "authentication", "authorization", "responsive design", "asynchronous programming",
            "schema design", "query optimization", "CI/CD", "Docker", "AWS", "Redis", "GraphQL", "Next.js",
        ],
        responsibilities=[
            "Design and maintain scalable database schemas and optimized queries",
            "Deliver responsive, user-friendly frontend interfaces",
            "Implement secure authentication and role-based access workflows",
        ],
        degree_requirements=["Bachelor's Degree"],
        experience_requirements=[],
        certifications=[],
    )

    # Mock LLM evaluation with strict semantic adherence
    mock_evaluator = MagicMock()
    async def mock_evaluate(reqs, evs, allowed):
        verdicts = []
        for r in reqs:
            t = r.text.casefold()
            if "authentication" in t:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="JWT token authentication in experience:1"))
            elif "authorization" in t:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="RBAC in experience:1"))
            elif "responsive" in t:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["project:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Responsive mobile-first UI in project:1"))
            elif "asynchronous" in t:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Async/await non-blocking endpoints in experience:1"))
            elif "schema design" in t:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:2"], method=MatchMethod.LLM_CONFIRMED, reasoning="Designed MongoDB schemas in experience:2"))
            elif "query optimization" in t:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:2"], method=MatchMethod.LLM_CONFIRMED, reasoning="Optimized database queries in experience:2"))
            elif "ci/cd" in t or "ci" in t:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:2"], method=MatchMethod.LLM_CONFIRMED, reasoning="GitHub Actions CI/CD pipelines in experience:2"))
            elif "docker" in t or "aws" in t or "redis" in t or "graphql" in t or "next.js" in t:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], method=MatchMethod.LLM_REJECTED, reasoning="No evidence in candidate profile"))
            else:
                verdicts.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.90, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="Experiential proof"))
        return verdicts

    mock_evaluator.evaluate = AsyncMock(side_effect=mock_evaluate)

    service = HybridMatchingService(evaluator=mock_evaluator)
    enriched, verdicts = await service.match(job, resume, extracted, config=None)

    verdict_by_text = {getattr(v, "requirement_text", ""): v for v in verdicts}

    # Verify POSITIVE semantic equivalents are confirmed
    assert verdict_by_text["authentication"].status == MatchStatus.MATCHED
    assert verdict_by_text["authorization"].status == MatchStatus.MATCHED
    assert verdict_by_text["responsive design"].status == MatchStatus.MATCHED
    assert verdict_by_text["asynchronous programming"].status == MatchStatus.MATCHED
    assert verdict_by_text["schema design"].status == MatchStatus.MATCHED
    assert verdict_by_text["query optimization"].status == MatchStatus.MATCHED
    assert verdict_by_text["CI/CD"].status == MatchStatus.MATCHED

    # Verify NEGATIVE unsupported skills are strictly rejected
    for missing in ["Docker", "AWS", "Redis", "GraphQL", "Next.js"]:
        assert verdict_by_text[missing].status == MatchStatus.NO_MATCH
