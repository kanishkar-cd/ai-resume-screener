import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    EvidenceBuilder, EvidencePrefilter, HybridMatchingService, RequirementBuilder,
    SemanticEvidenceRetriever, try_semantic_direct_match,
    normalize_technical_terms, is_genericity_safe, is_semantic_category_compatible,
)
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.core.config import Settings


# ============================================================================
# 1. CORE COSINE SIMILARITY CALCULATION & RANGE
# ============================================================================

def test_cosine_similarity_calculation_and_range():
    """Verify SemanticEvidenceRetriever calculates valid cosine similarity [0.0, 1.0]."""
    score_identical = SemanticEvidenceRetriever.cosine_similarity("FastAPI", "FastAPI")
    assert score_identical == 1.0

    score_empty = SemanticEvidenceRetriever.cosine_similarity("", "FastAPI")
    assert score_empty == 0.0

    score_distinct = SemanticEvidenceRetriever.cosine_similarity("AWS Cloud Infrastructure", "Ruby on Rails")
    assert 0.0 <= score_distinct < 0.50


# ============================================================================
# 2. TEST A: COSINE EVIDENCE RETRIEVAL SELECTS RELEVANT EVIDENCE
# ============================================================================

def test_A_cosine_evidence_retrieval_selects_relevant_evidence():
    """
    TEST A: Verify cosine >= 0.20 retains candidate evidence in EvidencePrefilter.select()
    so it can be evaluated further, without deciding a match.
    """
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="relational database schema design")
    ev = Evidence(
        evidence_id="experience:1",
        kind="experience",
        text="Architected and normalized relational database tables, SQL schemas, and indexes for large datasets.",
    )
    sim = SemanticEvidenceRetriever.cosine_similarity(req.text, ev.text)
    # Cosine is in the evidence-retrieval band (0.20 <= sim < 0.85)
    assert 0.20 <= sim < 0.85

    prefilter = EvidencePrefilter(threshold=0.15, limit=5, cosine_evidence_threshold=0.20)
    selected = prefilter.select(req, [ev])
    assert any(e.evidence_id == "experience:1" for e in selected)


# ============================================================================
# 3. TEST B & C: COSINE ALONE AND HIGH COSINE CANNOT PRODUCE MATCHED
# ============================================================================

def test_B_cosine_alone_cannot_produce_matched():
    """
    TEST B: A cosine score must NEVER directly create a final MATCHED verdict.
    try_semantic_direct_match is disabled and returns None.
    """
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Apache Kafka streaming")
    ev = Evidence(evidence_id="experience:1", kind="experience", text="Apache Kafka streaming platform")

    verdict = try_semantic_direct_match(req, [ev])
    assert verdict is None, "Cosine alone must NEVER produce a MATCHED verdict!"


def test_C_high_cosine_alone_cannot_produce_matched():
    """
    TEST C: Even with near-perfect cosine similarity (>= 0.85 or 1.0),
    cosine alone cannot produce MATCHED or bypass the LLM.
    """
    req = Requirement(requirement_id="skill:fastapi", kind=RequirementKind.SKILL, text="FastAPI")
    ev = Evidence(evidence_id="skills:fastapi", kind="skills", text="FastAPI")

    sim = SemanticEvidenceRetriever.cosine_similarity(req.text, ev.text)
    assert sim == 1.0

    # try_semantic_direct_match must still return None
    assert try_semantic_direct_match(req, [ev], threshold=0.85) is None


# ============================================================================
# 4. TEST D: LOW COSINE ALONE CANNOT PRODUCE UNMATCHED
# ============================================================================

def test_D_low_cosine_alone_cannot_produce_unmatched_when_valid_evidence_exists():
    """
    TEST D: Low cosine alone cannot produce UNMATCHED if another valid evidence path exists
    (such as strong lexical overlap or deterministic alias/concept).
    """
    req = Requirement(requirement_id="skill:react", kind=RequirementKind.SKILL, text="React")
    # Resume contains ReactJS (deterministic alias/concept match)
    resume = SimpleNamespace(skills=["ReactJS"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="ReactJS", canonical_terms=["React"])]

    service = HybridMatchingService(evaluator=MagicMock())
    matcher = service.matcher
    verdict = matcher.match(req, resume, evidence)

    assert verdict.status == MatchStatus.MATCHED
    assert verdict.method in {MatchMethod.ALIAS, MatchMethod.CONCEPT, MatchMethod.EXACT}


# ============================================================================
# 5. TEST E: EXACT / CANONICAL / ALIAS / CONCEPT MATCHES REMAIN AUTHORITATIVE
# ============================================================================

@pytest.mark.asyncio
async def test_E_deterministic_matches_remain_authoritative():
    """
    TEST E: Exact, canonical, alias, and controlled concept matches remain authoritative.
    They bypass evidence retrieval and LLM evaluation completely.
    """
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock()

    service = HybridMatchingService(evaluator=mock_evaluator)

    job = SimpleNamespace(
        required_skills=["Python", "ReactJS"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=["Python", "ReactJS"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    extracted = SimpleNamespace(
        candidate_name="Deterministic Candidate",
        skills=["Python", "ReactJS"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    enriched, fused = await service.match(job, resume, extracted)

    # LLM evaluator must never be called for deterministic matches!
    assert not mock_evaluator.evaluate.called

    v_python = next(v for v in fused if "Python" in getattr(v, "requirement_text", v.requirement_id))
    assert v_python.status == MatchStatus.MATCHED
    assert v_python.method == MatchMethod.EXACT

    v_react = next(v for v in fused if "React" in getattr(v, "requirement_text", v.requirement_id))
    assert v_react.status == MatchStatus.MATCHED
    assert v_react.method in {MatchMethod.ALIAS, MatchMethod.CONCEPT}


# ============================================================================
# 6. TEST F: LLM RECEIVES COSINE-RETRIEVED EVIDENCE FOR GRAY-ZONE CASES
# ============================================================================

@pytest.mark.asyncio
async def test_F_llm_receives_cosine_retrieved_evidence_for_gray_zone():
    """
    TEST F: Gray-zone requirements (deterministic miss) with cosine-retrieved evidence
    are submitted to LLM, and LLM receives the cosine-retrieved evidence IDs.
    """
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=([
        MatchVerdict(
            requirement_id="skill:1",
            requirement_text="relational database schema design",
            kind=RequirementKind.SKILL,
            status=MatchStatus.MATCHED,
            confidence=0.92,
            evidence_ids=["experience:1"],
            reasoning="Candidate designed PostgreSQL relational schemas in production.",
            method=MatchMethod.LLM_CONFIRMED,
            coverage=1.0,
            coverage_score=1.0,
        )
    ], {}))

    service = HybridMatchingService(evaluator=mock_evaluator)

    job = SimpleNamespace(
        required_skills=["relational database schema design"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=[],
        experience=[{
            "designation": "Database Engineer",
            "duration_months": 36,
            "description": "Architected and normalized relational database tables, SQL schemas, and indexes for large datasets.",
        }],
        projects=[],
        education=[],
        certifications=[],
    )
    extracted = SimpleNamespace(
        candidate_name="DB Engineer",
        skills=[],
        experience=resume.experience,
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    enriched, fused = await service.match(job, resume, extracted)

    # 1. LLM evaluator WAS called
    assert mock_evaluator.evaluate.called
    args, kwargs = mock_evaluator.evaluate.call_args
    unresolved_submitted = args[0]
    allowed_evidence = args[2]

    # 2. LLM received the requirement and allowed evidence containing experience:1
    assert any("relational" in req.text for req in unresolved_submitted)
    assert any("experience:1" in ev_set for ev_set in allowed_evidence.values())


# ============================================================================
# 7. TEST G: LLM RESULT BECOMES AUTHORITATIVE SEMANTIC VERDICT
# ============================================================================

@pytest.mark.asyncio
async def test_G_llm_result_becomes_authoritative_semantic_verdict_after_validation():
    """
    TEST G: The validated LLM decision becomes the authoritative semantic verdict.
    Its method is llm_confirmed (or llm_rejected), NOT cosine_direct.
    """
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=([
        MatchVerdict(
            requirement_id="skill:1",
            requirement_text="event-driven asynchronous messaging",
            kind=RequirementKind.SKILL,
            status=MatchStatus.MATCHED,
            confidence=0.88,
            evidence_ids=["experience:1"],
            reasoning="Demonstrated distributed streaming architecture using Apache Kafka in production.",
            method=MatchMethod.LLM_CONFIRMED,
            coverage=1.0,
            coverage_score=1.0,
        )
    ], {}))

    service = HybridMatchingService(evaluator=mock_evaluator)

    job = SimpleNamespace(
        required_skills=["event-driven asynchronous messaging"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
    )
    resume = SimpleNamespace(
        skills=[],
        experience=[{
            "designation": "Data Streaming Engineer",
            "duration_months": 24,
            "description": "Architected high-throughput distributed event pub-sub streaming with Apache Kafka.",
        }],
        projects=[],
        education=[],
        certifications=[],
    )
    extracted = SimpleNamespace(
        candidate_name="Kafka Engineer",
        skills=[],
        experience=resume.experience,
        projects=[],
        education=[],
        certifications=[],
        languages=[],
    )

    enriched, fused = await service.match(job, resume, extracted)

    v = fused[0]
    assert v.status == MatchStatus.MATCHED
    assert v.method == MatchMethod.LLM_CONFIRMED
    assert v.method != MatchMethod.COSINE_DIRECT


# ============================================================================
# 8. TEST H: COSINE DOES NOT DIRECTLY AFFECT FINAL CANDIDATE SCORE
# ============================================================================

def test_H_cosine_does_not_directly_affect_final_candidate_score():
    """
    TEST H: Final candidate score in ComponentScoringService is derived purely from
    verdict status (MATCHED / PARTIAL) and coverage_score.
    A verdict having a cosine_score vs not having one produces the exact same score.
    """
    scoring = ComponentScoringService()

    job = SimpleNamespace(
        skills=["Python", "FastAPI"],
        required_skills=["Python", "FastAPI"],
        preferred_skills=[],
        responsibilities=[],
        degree_requirements=[],
        experience_requirements=[],
        project_requirements=[],
        certifications=[],
    )
    resume = SimpleNamespace(
        skills=["Python", "FastAPI"],
        experience=[],
        projects=[],
        education=[],
        certifications=[],
    )
    config = SimpleNamespace(required_certifications=[])

    # Verdicts with cosine_score populated
    verdicts_with_cosine = [
        MatchVerdict(
            requirement_id="skill:1",
            requirement_text="Python",
            kind=RequirementKind.REQUIRED_SKILL,
            status=MatchStatus.MATCHED,
            coverage=1.0,
            coverage_score=1.0,
            confidence=0.95,
            cosine_score=0.95,
            method=MatchMethod.LLM_CONFIRMED,
        ),
        MatchVerdict(
            requirement_id="skill:2",
            requirement_text="FastAPI",
            kind=RequirementKind.REQUIRED_SKILL,
            status=MatchStatus.MATCHED,
            coverage=1.0,
            coverage_score=1.0,
            confidence=0.88,
            cosine_score=0.88,
            method=MatchMethod.LLM_CONFIRMED,
        ),
    ]

    # Identical verdicts with cosine_score=None
    verdicts_without_cosine = [
        MatchVerdict(
            requirement_id="skill:1",
            requirement_text="Python",
            kind=RequirementKind.REQUIRED_SKILL,
            status=MatchStatus.MATCHED,
            coverage=1.0,
            coverage_score=1.0,
            confidence=0.95,
            cosine_score=None,
            method=MatchMethod.LLM_CONFIRMED,
        ),
        MatchVerdict(
            requirement_id="skill:2",
            requirement_text="FastAPI",
            kind=RequirementKind.REQUIRED_SKILL,
            status=MatchStatus.MATCHED,
            coverage=1.0,
            coverage_score=1.0,
            confidence=0.88,
            cosine_score=None,
            method=MatchMethod.LLM_CONFIRMED,
        ),
    ]

    scores_with = scoring.score(resume, job, config, projects=[], match_verdicts=verdicts_with_cosine)
    scores_without = scoring.score(resume, job, config, projects=[], match_verdicts=verdicts_without_cosine)

    # Candidate component scores must be identical
    assert scores_with.skills.score == scores_without.skills.score
    assert scores_with.experience.score == scores_without.experience.score
    assert scores_with.projects.score == scores_without.projects.score


# ============================================================================
# 9. OBSERVABILITY TELEMETRY TEST
# ============================================================================

def test_cosine_retrieval_observability_tracking():
    """Verify that EvidencePrefilter captures all required observability fields."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="relational database schema")
    ev = Evidence(
        evidence_id="experience:1",
        kind="experience",
        text="Architected and normalized relational database tables and SQL schemas.",
    )

    prefilter = EvidencePrefilter(threshold=0.15, limit=5, cosine_evidence_threshold=0.20)
    selected = prefilter.select(req, [ev])

    telemetry = prefilter.retrieval_telemetry.get("skill:1", [])
    assert len(telemetry) == 1
    rec = telemetry[0]
    assert rec["requirement_id"] == "skill:1"
    assert rec["evidence_id"] == "experience:1"
    assert "cosine_score" in rec
    assert rec["evidence_selected"] is True
    assert rec["retrieval_source"] in {"lexical", "cosine", "both"}


# ============================================================================
# 10. REPRESENTATION, NORMALIZATION & CATEGORY SAFETY TESTS
# ============================================================================

def test_technical_term_normalization():
    """Verify technical variations normalize cleanly while broad concepts do not collapse."""
    assert normalize_technical_terms("python3") == "python"
    assert normalize_technical_terms("Python 3") == "python"
    assert normalize_technical_terms("react.js") == "react"
    assert normalize_technical_terms("reactjs") == "react"
    assert normalize_technical_terms("node.js") == "node"
    assert normalize_technical_terms("nodejs") == "node"
    assert normalize_technical_terms("postgres") == "postgresql"
    assert normalize_technical_terms("postgresql db") == "postgresql"
    assert normalize_technical_terms("k8s") == "kubernetes"
    assert normalize_technical_terms("kubernetes orchestration") == "kubernetes"

    # Broad concepts MUST NOT collapse to specific technologies
    assert normalize_technical_terms("database") == "database"
    assert normalize_technical_terms("cloud") == "cloud"
    assert normalize_technical_terms("container") == "container"
    assert normalize_technical_terms("programming") == "programming"


def test_generic_words_suppressed_in_cosine():
    """Verify generic resume buzzwords (development, management, etc.) do not dominate cosine similarity."""
    s1 = "Strong experience in application development, system management, and technical solutions using Python"
    s2 = "Strong experience in application development, system management, and technical solutions using Ruby"

    sim = SemanticEvidenceRetriever.cosine_similarity(s1, s2)
    assert sim < 0.35, f"Generic buzzwords dominated cosine similarity! Score: {sim}"


def test_genericity_safety_gate():
    """Verify broad requirements cannot direct-match specific technologies, and vice-versa."""
    safe, reason = is_genericity_safe("database", "PostgreSQL database management")
    assert safe is True

    safe_block, reason = is_genericity_safe("database", "PostgreSQL indexes and query optimization")
    assert safe_block is False
    assert "Generic requirement" in reason

    safe_spec_block, reason2 = is_genericity_safe("PostgreSQL", "Extensive relational database and data management experience")
    assert safe_spec_block is False
    assert "cannot be satisfied by generic category mention" in reason2


def test_semantic_category_compatibility_gate():
    """Verify incompatible semantic categories (e.g. database vs frontend) are blocked."""
    compat, reason = is_semantic_category_compatible("PostgreSQL database", "React frontend components and CSS styling")
    assert compat is False
    assert "Semantic category mismatch" in reason


def test_configurable_token_weights():
    """Verify that custom weights in Settings alter embedding vector generation appropriately."""
    custom_settings = Settings(
        COSINE_TECHNICAL_TOKEN_WEIGHT=5.0,
        COSINE_EXACT_TOKEN_WEIGHT=2.0,
        COSINE_STEM_WEIGHT=1.0,
        COSINE_NGRAM_WEIGHT=0.1,
        COSINE_GENERIC_TOKEN_WEIGHT=0.01,
    )

    v1 = SemanticEvidenceRetriever.embedding_vector("Python", settings=custom_settings)
    assert len(v1) == 256
    assert any(x > 0 for x in v1)
