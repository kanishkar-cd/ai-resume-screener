import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx

from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, EvidencePrefilter,
    GroqMatchEvaluator, HybridMatchingService, RequirementBuilder,
)
from app.services.scoring import ComponentScoringService, WeightCalculationService


# ==============================================================================
# 1. DETERMINISTIC VS LLM ROUTING (TESTS 1 - 3)
# ==============================================================================

@pytest.mark.asyncio
async def test_1_canonical_match_no_llm():
    """1. Direct canonical match (e.g. React) -> MATCHED, 0 LLM calls."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["React", "Node.js"], experience=[], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["React", "Node.js"], experience=[], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["React"], preferred_skills=[], skills=["React"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method == MatchMethod.EXACT
    mock_evaluator.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_2_alias_match_no_llm():
    """2. Strong alias match (e.g. Node for Node.js) -> MATCHED, 0 LLM calls."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["Node"], experience=[], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["Node"], experience=[], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["Node.js"], preferred_skills=[], skills=["Node.js"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method == MatchMethod.ALIAS
    mock_evaluator.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_3_canonical_failure_llm_fallback():
    """3. Canonical failure with genuine evidence -> LLM fallback."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[
        MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.92, evidence_ids=["experience:1"], method=MatchMethod.LLM_CONFIRMED, reasoning="JWT satisfies authentication")
    ])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=[], experience=[{"description": "Implemented JWT token authentication"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=[], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["authentication"], preferred_skills=[], skills=["authentication"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method == MatchMethod.LLM_CONFIRMED
    mock_evaluator.evaluate.assert_called_once()


# ==============================================================================
# 2. SEMANTIC EQUIVALENCE & TECHNICAL EVIDENCE (TESTS 4 - 10)
# ==============================================================================

@pytest.mark.asyncio
async def test_4_jwt_to_authentication():
    """4. JWT -> authentication semantic match."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authentication")
    ev = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented JWT authentication")]
    assert len(prefilter.select(req, ev)) == 1


@pytest.mark.asyncio
async def test_5_rbac_to_authorization():
    """5. RBAC -> authorization semantic match."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")
    ev = [Evidence(evidence_id="experience:1", kind="experience", text="Configured RBAC access workflows")]
    assert len(prefilter.select(req, ev)) == 1


@pytest.mark.asyncio
async def test_6_async_await_to_asynchronous_programming():
    """6. async/await -> asynchronous programming."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="asynchronous programming")
    ev = [Evidence(evidence_id="experience:1", kind="experience", text="Implemented async/await promises")]
    assert len(prefilter.select(req, ev)) == 1


@pytest.mark.asyncio
async def test_7_event_driven_to_asynchronous_programming():
    """7. event-driven -> asynchronous programming."""
    prefilter = EvidencePrefilter(threshold=0.20, limit=6)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="asynchronous programming")
    ev = [Evidence(evidence_id="experience:1", kind="experience", text="Architected event-driven microservices")]
    assert len(prefilter.select(req, ev)) == 1


@pytest.mark.asyncio
async def test_8_rest_to_rest_apis():
    """8. REST -> REST APIs."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="REST APIs")
    resume = SimpleNamespace(skills=["REST"], experience=[], projects=[], education=[], certifications=[], languages=[])
    verdict = matcher.match(req, resume, [])
    assert verdict.status == MatchStatus.MATCHED


def test_9_mongodb_and_postgresql_database_requirement():
    """9. MongoDB + PostgreSQL -> 'Relational and non-relational databases' (2/2 = 100%)."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Relational and non-relational databases")
    ev = [Evidence(evidence_id="experience:1", kind="experience", text="Designed relational databases and non-relational databases")]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Designed relational databases and non-relational databases"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    v = matcher.match(req, resume, ev)
    assert v.status == MatchStatus.MATCHED
    assert v.coverage == 1.00
    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[v])
    assert scores.responsibilities.score == 100.0


def test_10_mongodb_only_partial_database_requirement():
    """10. MongoDB only -> 'Relational and non-relational databases' (1/2 = 50% PARTIAL)."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Relational and non-relational databases")
    ev = [Evidence(evidence_id="experience:1", kind="experience", text="Designed non-relational databases")]
    resume = SimpleNamespace(skills=[], experience=[{"description": "Designed non-relational databases"}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    v = matcher.match(req, resume, ev)
    assert v.status == MatchStatus.PARTIALLY_MATCHED
    assert v.coverage == 0.50
    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[v])
    assert scores.responsibilities.score == 50.0


# ==============================================================================
# 3. RESPONSIBILITY CONCEPT DECOMPOSITION (TESTS 11 - 14)
# ==============================================================================

@pytest.mark.parametrize("satisfied_count,expected_status,expected_coverage,expected_score", [
    (1, MatchStatus.PARTIALLY_MATCHED, 0.20, 20.0),
    (2, MatchStatus.MATCHED, 0.40, 40.0),
    (3, MatchStatus.MATCHED, 0.60, 60.0),
    (5, MatchStatus.MATCHED, 1.00, 100.0),
])
def test_11_to_14_partial_responsibility_scoring(satisfied_count, expected_status, expected_coverage, expected_score):
    """11-14: 1/5(20%), 2/5(40%), 3/5(60%), 5/5(100%)."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Develop scalable applications using MongoDB, Express.js, React.js, and Node.js",
    )
    concept_phrases = ["scalable applications", "MongoDB", "Express.js", "React.js", "Node.js"]
    ev_text = ", ".join(concept_phrases[:satisfied_count])
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text=ev_text)]
    resume = SimpleNamespace(skills=[], experience=[{"description": ev_text}], projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=[], preferred_skills=[], skills=[], responsibilities=[req.text], degree_requirements=[], experience_requirements=[], certifications=[])

    v = matcher.match(req, resume, evidence)
    assert v.status == expected_status
    assert round(v.coverage, 2) == round(expected_coverage, 2)
    scores = scoring_svc.score(resume, job, config=None, match_verdicts=[v])
    assert round(scores.responsibilities.score, 1) == round(expected_score, 1)


# ==============================================================================
# 4. VERDICT & EVIDENCE ID VALIDATION (TESTS 15 - 19)
# ==============================================================================

@pytest.mark.asyncio
async def test_15_missing_requirement_no_match():
    """15. Missing requirement with 0 evidence -> NO_MATCH (0 LLM calls)."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["Python"], experience=[{"description": "Wrote Python code"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["Python"], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["Kubernetes"], preferred_skills=[], skills=["Kubernetes"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    assert verdicts[0].status == MatchStatus.NO_MATCH
    mock_evaluator.evaluate.assert_not_called()


def test_16_genuine_ambiguity_unresolved():
    """16. Genuine ambiguity -> UNRESOLVED."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Lead complex cloud migration")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Assisted team with cloud setup")]
    allowed = {"responsibility:1": {"experience:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.UNRESOLVED, confidence=0.45, evidence_ids=["experience:1"], reasoning="Ambiguous evidence whether candidate led the effort")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert validated[0].status == MatchStatus.UNRESOLVED


def test_17_valid_llm_evidence_ai_confirmed():
    """17. Valid semantic LLM evidence -> AI_CONFIRMED (MATCHED)."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Enforced RBAC policies")]
    allowed = {"skill:1": {"experience:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:1"], reasoning="RBAC confirms authorization")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED


def test_18_invalid_evidence_id_rejected():
    """18. Invalid evidence ID -> rejected to UNRESOLVED."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Enforced RBAC policies")]
    allowed = {"skill:1": {"experience:1"}}

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["experience:999"], reasoning="Invalid citation")
    ])
    validated = evaluator._validate(batch, reqs, evs, allowed)
    assert validated[0].status == MatchStatus.UNRESOLVED
    assert "Rejected: No valid candidate evidence ID cited for match" in validated[0].reasoning


def test_19_equivalent_evidence_id_formatting_accepted():
    """19. Equivalent ID formatting ('Experience:1', 'experience 1') -> normalized and accepted."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="authorization")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Enforced RBAC policies")]
    allowed = {"skill:1": {"experience:1"}}

    for raw_id in ["Experience:1", "experience 1", "Experience #1", "experience-1"]:
        batch = LLMVerdictBatch(verdicts=[
            LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=[raw_id], reasoning="Variant citation")
        ])
        validated = evaluator._validate(batch, reqs, evs, allowed)
        assert validated[0].status == MatchStatus.MATCHED
        assert validated[0].evidence_ids == ["experience:1"]


# ==============================================================================
# 5. BATCHING, CACHING & EFFICIENCY (TESTS 20 - 23)
# ==============================================================================

def test_20_duplicate_requirements_one_evaluation():
    """20. Duplicate requirements in job description deduplicated during build."""
    job = SimpleNamespace(required_skills=["React", "React", "react"], preferred_skills=[], skills=["React"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])
    reqs = RequirementBuilder.build(job, config=None)
    assert len(reqs) == 1
    assert reqs[0].text == "React"


@pytest.mark.asyncio
async def test_21_cached_evaluation_zero_http_calls(monkeypatch):
    """21. Cached LLM evaluation avoids repeated HTTP calls."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="cloud architecture")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Designed AWS cloud infrastructure")]
    allowed = {"skill:1": {"experience:1"}}

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{
            "message": {
                "content": '{"verdicts":[{"requirement_id":"skill:1","status":"MATCHED","confidence":0.9,"evidence_ids":["experience:1"],"reasoning":"AWS cloud"}]}'
            }
        }]
    }
    mock_resp.raise_for_status = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")

    # 1st call -> HTTP call executed
    v1 = await evaluator.evaluate(reqs, evs, allowed)
    assert len(v1) == 1
    assert mock_client.post.call_count == 1

    # 2nd call -> Returns from SHA-256 cache, 0 HTTP calls
    v2 = await evaluator.evaluate(reqs, evs, allowed)
    assert len(v2) == 1
    assert mock_client.post.call_count == 1


@pytest.mark.asyncio
async def test_22_large_batch_safely_split(monkeypatch):
    """22. Large requirement batch (>15) is split into manageable chunks."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id=f"skill:{i+1}", kind=RequirementKind.REQUIRED_SKILL, text=f"Skill {i+1}") for i in range(25)]
    evs = [Evidence(evidence_id=f"experience:{i+1}", kind="experience", text=f"Evidence {i+1}") for i in range(25)]
    allowed = {f"skill:{i+1}": {f"experience:{i+1}"} for i in range(25)}

    import json
    call_count = 0
    async def mock_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        payload = kwargs.get("json", {})
        sub_reqs = json.loads(payload["messages"][1]["content"])["requirements"] if "content" in payload["messages"][1] else []
        verdicts = [
            {"requirement_id": r["requirement_id"], "status": "MATCHED", "confidence": 0.9, "evidence_ids": [f"experience:{r['requirement_id'].split(':')[1]}"], "reasoning": "Matched"}
            for r in sub_reqs
        ]
        resp = MagicMock()
        resp.json.return_value = {"choices": [{"message": {"content": json.dumps({"verdicts": verdicts})}}]}
        resp.raise_for_status = MagicMock()
        return resp

    mock_client = MagicMock()
    mock_client.post = mock_post
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")

    verdicts = await evaluator.evaluate(reqs, evs, allowed)
    assert len(verdicts) == 25
    assert call_count >= 2  # Proves chunking occurred


@pytest.mark.asyncio
async def test_23_429_bounded_retry(monkeypatch):
    """23. HTTP 429 respects Retry-After with exponential backoff."""
    evaluator = GroqMatchEvaluator()
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="Docker")]
    evs = [Evidence(evidence_id="experience:1", kind="experience", text="Dockerized apps")]
    allowed = {"skill:1": {"experience:1"}}

    import json
    attempts = 0
    async def mock_post(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            resp_429 = MagicMock()
            resp_429.status_code = 429
            resp_429.headers = {"Retry-After": "0.01"}
            resp_429.text = "Rate limited"
            err = httpx.HTTPStatusError("429 Too Many Requests", request=MagicMock(), response=resp_429)
            raise err
        resp_200 = MagicMock()
        resp_200.json.return_value = {
            "choices": [{
                "message": {
                    "content": json.dumps({
                        "verdicts": [{
                            "requirement_id": "skill:1",
                            "status": "MATCHED",
                            "confidence": 0.9,
                            "evidence_ids": ["experience:1"],
                            "reasoning": "Docker match"
                        }]
                    })
                }
            }]
        }
        resp_200.raise_for_status = MagicMock()
        return resp_200

    mock_client = MagicMock()
    mock_client.post = mock_post
    monkeypatch.setattr(GroqMatchEvaluator, "_get_client", lambda cls, timeout: mock_client)
    monkeypatch.setattr(evaluator.settings, "ENABLE_HYBRID_MATCHING", True)
    monkeypatch.setattr(evaluator.settings, "GROQ_API_KEY", "mock_key")
    monkeypatch.setattr(evaluator.settings, "GROQ_MAX_RETRIES", 2)

    verdicts = await evaluator.evaluate(reqs, evs, allowed)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert attempts == 2


# ==============================================================================
# 6. ANTI-HALLUCINATION & TAXONOMY (TESTS 24 - 26)
# ==============================================================================

@pytest.mark.asyncio
async def test_24_no_hallucinated_technology_matches():
    """24. Strict anti-hallucination barriers."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])
    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["JavaScript"], experience=[{"description": "Built JavaScript frontends"}], projects=[], education=[], certifications=[], languages=[])
    extracted = SimpleNamespace(skills=["JavaScript"], experience=resume.experience, projects=[], education=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["Next.js", "Docker", "AWS"], preferred_skills=[], skills=["Next.js", "Docker", "AWS"], responsibilities=[], degree_requirements=[], experience_requirements=[], certifications=[])

    enriched, verdicts = await service.match(job, resume, extracted, config=None)
    for v in verdicts:
        assert v.status == MatchStatus.NO_MATCH


def test_25_experience_arithmetic_no_llm():
    """25. 5+ years and 5-8 years satisfied deterministically by 7.7 years (0 LLM calls)."""
    matcher = DeterministicRequirementMatcher()
    resume = SimpleNamespace(skills=[], experience=[{"duration_months": 92}], projects=[], education=[], certifications=[], languages=[])

    # 5+ years
    req_5plus = Requirement(requirement_id="exp:1", kind=RequirementKind.EXPERIENCE, text="5+ years of software experience")
    v_5plus = matcher.match(req_5plus, resume, [])
    assert v_5plus.status == MatchStatus.MATCHED
    assert v_5plus.method == MatchMethod.EXACT

    # 5-8 years
    req_5to8 = Requirement(requirement_id="exp:2", kind=RequirementKind.EXPERIENCE, text="5-8 years of experience")
    v_5to8 = matcher.match(req_5to8, resume, [])
    assert v_5to8.status == MatchStatus.MATCHED
    assert v_5to8.method == MatchMethod.EXACT


def test_26_degree_taxonomy_no_llm():
    """26. Education degree matching disabled -> NO_MATCH."""
    matcher = DeterministicRequirementMatcher()
    resume = SimpleNamespace(skills=[], experience=[], projects=[], education=[{"degree": "Bachelor of Technology", "field_of_study": "Computer Science"}], certifications=[], languages=[])
    req = Requirement(requirement_id="deg:1", kind=RequirementKind.DEGREE, text="Bachelor's Degree in Computer Science or related field")
    v = matcher.match(req, resume, [])
    assert v.status == MatchStatus.NO_MATCH


# ==============================================================================
# 7. THREE-RESUME PROFILES: JUNIOR, MID, LEAD (TEST 27)
# ==============================================================================

@pytest.mark.asyncio
async def test_27_three_resume_profiles_junior_mid_lead():
    """27. Validate Junior (Aditi), Mid (Rohan), Lead (Vikram) against Senior Full-Stack Lead JD."""
    comp_svc = ComponentScoringService()
    weight_svc = WeightCalculationService()

    # Deterministic mock evaluator for semantic fallback
    mock_evaluator = MagicMock()
    async def mock_evaluate(reqs, evs, allowed):
        res = []
        for r in reqs:
            ev_for_r = list(allowed.get(r.requirement_id, set())) if allowed else []
            if "mentor" in r.text.casefold() or "cloud" in r.text.casefold() or "microservices" in r.text.casefold():
                if ev_for_r:
                    res.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=ev_for_r, method=MatchMethod.LLM_CONFIRMED, reasoning="Confirmed"))
                else:
                    res.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.NO_MATCH, confidence=0.9, method=MatchMethod.LLM_REJECTED, reasoning="No evidence"))
            else:
                res.append(MatchVerdict(requirement_id=r.requirement_id, status=MatchStatus.NO_MATCH, confidence=0.9, method=MatchMethod.LLM_REJECTED, reasoning="No evidence"))
        return res
    mock_evaluator.evaluate = mock_evaluate
    hybrid_svc = HybridMatchingService(evaluator=mock_evaluator)

    job = SimpleNamespace(
        title="Senior Full-Stack Lead",
        required_skills=["React", "Node.js", "TypeScript", "Microservices", "Cloud Architecture", "Docker", "CI/CD"],
        preferred_skills=["Redis", "GraphQL"],
        skills=["React", "Node.js", "TypeScript", "Microservices", "Cloud Architecture", "Docker", "CI/CD"],
        responsibilities=[
            "Architect scalable distributed microservices and cloud infrastructure",
            "Lead and mentor engineering team members through code reviews and technical guidance",
            "Deliver responsive frontend applications and automated CI/CD deployment pipelines",
        ],
        degree_requirements=["Bachelor's Degree in Computer Science or related field"],
        experience_requirements=["5+ years of software engineering experience"],
        certifications=["AWS Certified Solutions Architect"],
        passing_score=50.0,
    )

    # 1. Junior: Aditi Sharma (~1.5 yrs, MERN basic, responsive, no cloud arch, no mentoring)
    res_junior = SimpleNamespace(
        name="Aditi Sharma",
        skills=["React", "Node.js", "JavaScript", "HTML5", "CSS3"],
        experience=[{"duration_months": 18, "description": "Built responsive React components and basic Express endpoints with developers"}],
        projects=[{"name": "App", "description": "Built full stack MERN app"}],
        education=[{"degree": "B.Tech", "field_of_study": "Computer Science"}],
        certifications=[],
        languages=["English"],
    )
    ext_junior = SimpleNamespace(
        skills=res_junior.skills, experience=res_junior.experience, projects=res_junior.projects,
        education=res_junior.education, certifications=[], languages=res_junior.languages,
    )

    # 2. Mid: Rohan Mehta (~4.5 yrs, MERN + TypeScript + Docker + CI/CD + MongoDB tuning)
    res_mid = SimpleNamespace(
        name="Rohan Mehta",
        skills=["React", "Node.js", "TypeScript", "Docker", "CI/CD", "MongoDB"],
        experience=[{"duration_months": 54, "description": "Engineered TypeScript microservices, configured Docker containers, and built CI/CD deployment pipelines"}],
        projects=[{"name": "Dashboard", "description": "Engineered responsive UI and tuned MongoDB query indexes"}],
        education=[{"degree": "Bachelor of Engineering", "field_of_study": "Information Technology"}],
        certifications=[],
        languages=["English"],
    )
    ext_mid = SimpleNamespace(
        skills=res_mid.skills, experience=res_mid.experience, projects=res_mid.projects,
        education=res_mid.education, certifications=[], languages=res_mid.languages,
    )

    # 3. Lead: Vikram Nair (~9 yrs, Full Stack + Cloud Architecture AWS + Microservices + Mentoring + AWS Cert)
    res_lead = SimpleNamespace(
        name="Vikram Nair",
        skills=["React", "Node.js", "TypeScript", "Microservices", "Cloud Architecture", "Docker", "CI/CD", "AWS", "Redis"],
        experience=[{"duration_months": 108, "description": "Architected scalable cloud infrastructure on AWS, led microservices modernization, and mentored junior developers and team members"}],
        projects=[{"name": "Cloud Platform", "description": "Architected distributed microservices on AWS and automated CI/CD deployment pipelines"}],
        education=[{"degree": "Master of Science", "field_of_study": "Computer Science"}],
        certifications=[{"name": "AWS Certified Solutions Architect"}],
        languages=["English"],
    )
    ext_lead = SimpleNamespace(
        skills=res_lead.skills, experience=res_lead.experience, projects=res_lead.projects,
        education=res_lead.education, certifications=res_lead.certifications, languages=res_lead.languages,
    )

    # Evaluate all 3 candidates
    _, v_junior = await hybrid_svc.match(job, res_junior, ext_junior)
    scores_junior = comp_svc.score(res_junior, job, config=None, match_verdicts=v_junior)
    _, _, final_junior, _ = weight_svc.calculate(scores_junior)

    _, v_mid = await hybrid_svc.match(job, res_mid, ext_mid)
    scores_mid = comp_svc.score(res_mid, job, config=None, match_verdicts=v_mid)
    _, _, final_mid, _ = weight_svc.calculate(scores_mid)

    _, v_lead = await hybrid_svc.match(job, res_lead, ext_lead)
    scores_lead = comp_svc.score(res_lead, job, config=None, match_verdicts=v_lead)
    _, _, final_lead, _ = weight_svc.calculate(scores_lead)

    # Assert rigorous proportional ranking: Lead > Mid > Junior
    assert final_lead > final_mid > final_junior
    assert final_junior < 60.0  # Junior correctly rejected/reviewed for Senior Lead role
    assert final_lead >= 80.0   # Lead receives strong score (>84)
