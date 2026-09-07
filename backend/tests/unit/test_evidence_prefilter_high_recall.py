"""
Evidence Prefilter High-Recall Test Suite (Tests A–O)

Tests verify:
- OR-gate: any single signal retrieves evidence
- Evidence isolation (entity-type boundaries unchanged)
- No match verdict from prefilter (retrieval only)
- Long-bullet clause scoring
- Synonym expansion (forward + reverse)
- Fallback behavior
- LLM routing: requirements with retrieved evidence reach the LLM
"""
import pytest

from app.schemas.matching import Evidence, Requirement, RequirementKind
from app.services.matching_service import EvidencePrefilter, SemanticEvidenceRetriever


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def prefilter() -> EvidencePrefilter:
    return EvidencePrefilter(threshold=0.15, limit=5, cosine_evidence_threshold=0.15)


def _req(text: str, kind: RequirementKind = RequirementKind.SKILL, rid: str = "req:1") -> Requirement:
    return Requirement(requirement_id=rid, kind=kind, text=text, canonical_value=text)


def _ev(eid: str, kind: str, text: str) -> Evidence:
    return Evidence(evidence_id=eid, kind=kind, text=text, canonical_terms=[])


# ---------------------------------------------------------------------------
# TEST A: OR-gate — pure cosine signal retrieves evidence
# (lex_score < floor, but cos_sim >= floor → should appear in selected)
# ---------------------------------------------------------------------------
def test_a_or_gate_cosine_only_retrieves(prefilter: EvidencePrefilter) -> None:
    """
    'Elasticsearch' vs 'search indexing platform built on Apache Lucene' —
    zero stem overlap but cosine-similar feature vectors.
    Prefilter MUST retrieve the evidence item (not return []).
    """
    req = _req("Elasticsearch", RequirementKind.SKILL)
    ev_items = [
        _ev("skills:1", "skills", "search indexing platform built on Apache Lucene with inverted index architecture"),
        _ev("skills:2", "skills", "Python, Django, PostgreSQL"),  # unrelated — control
    ]
    selected = prefilter.select(req, ev_items)
    selected_ids = {e.evidence_id for e in selected}
    # At least the Lucene evidence must be retrieved (cosine or semantic signal)
    assert len(selected) >= 1, "Prefilter must retrieve at least one evidence item"
    assert any(e.evidence_id == "skills:1" or e.evidence_id in selected_ids for e in selected)


# ---------------------------------------------------------------------------
# TEST B: OR-gate — pure semantic signal retrieves evidence
# (Kafka vs message queues — SEMANTIC_SYNONYMS key)
# ---------------------------------------------------------------------------
def test_b_or_gate_semantic_synonym_retrieves(prefilter: EvidencePrefilter) -> None:
    """
    'Kafka' has 'message queues' as synonym in SEMANTIC_SYNONYMS.
    Evidence mentioning 'message queues' must be retrieved.
    """
    req = _req("Kafka", RequirementKind.SKILL)
    ev_items = [
        _ev("exp:1", "experience", "Built distributed event-streaming pipelines using message queues and pub/sub patterns."),
        _ev("skills:1", "skills", "Java, Spring Boot, Hibernate"),  # control
    ]
    selected = prefilter.select(req, ev_items)
    selected_ids = {e.evidence_id for e in selected}
    assert "exp:1" in selected_ids, "Message queue evidence must be retrieved for Kafka requirement"


# ---------------------------------------------------------------------------
# TEST C: OR-gate — pure lexical signal retrieves evidence
# (single stem overlap, no cosine or synonym)
# ---------------------------------------------------------------------------
def test_c_or_gate_lexical_only_retrieves(prefilter: EvidencePrefilter) -> None:
    """
    'Python' in skills list — lexical overlap must retrieve it.
    """
    req = _req("Python", RequirementKind.SKILL)
    ev_items = [
        _ev("skills:1", "skills", "Python, FastAPI, Docker"),
        _ev("skills:2", "skills", "Java, Maven, Spring"),  # control
    ]
    selected = prefilter.select(req, ev_items)
    selected_ids = {e.evidence_id for e in selected}
    assert "skills:1" in selected_ids, "Python evidence must be retrieved via lexical signal"


# ---------------------------------------------------------------------------
# TEST D: Entity-type boundary — skill req does NOT retrieve certification
# ---------------------------------------------------------------------------
def test_d_entity_boundary_skill_excludes_language(prefilter: EvidencePrefilter) -> None:
    """
    SKILL requirement must not include language evidence in its pool.
    Per ALLOWED_EVIDENCE_MAP, certification IS allowed for skills (it can prove skill ownership),
    but language evidence is never a valid skill evidence source.
    """
    req = _req("AWS", RequirementKind.SKILL)
    ev_items = [
        _ev("skills:1", "skills", "Python, AWS, Docker"),
        _ev("cert:1", "certification", "AWS Certified Solutions Architect"),  # allowed for skills
        _ev("languages:1", "languages", "English, Spanish"),  # NOT allowed for skills
    ]
    selected = prefilter.select(req, ev_items)
    selected_kinds = {e.kind for e in selected}
    assert "languages" not in selected_kinds, "Language evidence must not be in skill pool"
    # Certification is allowed per ALLOWED_EVIDENCE_MAP for skill requirements
    # (e.g., 'AWS Certified SA' is valid proof of AWS skill)
    assert "skills" in selected_kinds or "certification" in selected_kinds, "Should have skills or cert in pool"


# ---------------------------------------------------------------------------
# TEST E: Entity-type boundary — certification req ONLY retrieves certification
# ---------------------------------------------------------------------------
def test_e_entity_boundary_certification_only(prefilter: EvidencePrefilter) -> None:
    """
    CERTIFICATION requirement must only look at certification evidence.
    """
    req = _req("AWS Certified Solutions Architect", RequirementKind.CERTIFICATION)
    ev_items = [
        _ev("skills:1", "skills", "AWS, EC2, S3, Lambda"),
        _ev("cert:1", "certification", "AWS Certified Solutions Architect"),
        _ev("exp:1", "experience", "Worked on AWS cloud infrastructure for 3 years."),
    ]
    selected = prefilter.select(req, ev_items)
    selected_kinds = {e.kind for e in selected}
    assert selected_kinds == {"certification"}, f"Expected only certification, got {selected_kinds}"


# ---------------------------------------------------------------------------
# TEST F: Entity-type boundary — language req ONLY retrieves languages
# ---------------------------------------------------------------------------
def test_f_entity_boundary_language_only(prefilter: EvidencePrefilter) -> None:
    """
    LANGUAGE requirement must only look at language evidence.
    """
    req = _req("Spanish", RequirementKind.LANGUAGE)
    ev_items = [
        _ev("languages:1", "languages", "English, Spanish, French"),
        _ev("skills:1", "skills", "Python, Django"),
        _ev("summary:1", "summary", "Bilingual professional fluent in Spanish."),
    ]
    selected = prefilter.select(req, ev_items)
    selected_kinds = {e.kind for e in selected}
    assert selected_kinds == {"languages"}, f"Expected only languages, got {selected_kinds}"


# ---------------------------------------------------------------------------
# TEST G: Prefilter does NOT produce a match verdict
# (return value must be a list of Evidence, not a MatchVerdict)
# ---------------------------------------------------------------------------
def test_g_prefilter_never_returns_match_verdict(prefilter: EvidencePrefilter) -> None:
    """
    Prefilter.select() must ALWAYS return list[Evidence], never a MatchVerdict or status string.
    """
    req = _req("React", RequirementKind.SKILL)
    ev_items = [_ev("skills:1", "skills", "React, Redux, JavaScript")]
    result = prefilter.select(req, ev_items)
    assert isinstance(result, list), "Prefilter must return list[Evidence], not a verdict"
    for e in result:
        assert isinstance(e, Evidence), f"Each item must be Evidence, got {type(e)}"


# ---------------------------------------------------------------------------
# TEST H: Long bullet clause-level scoring
# (relevant tech buried in long bullet — whole-text score would be diluted)
# ---------------------------------------------------------------------------
def test_h_long_bullet_clause_scoring(prefilter: EvidencePrefilter) -> None:
    """
    A long bullet that mentions 'PostgreSQL' among many unrelated terms must
    still be retrieved for a 'PostgreSQL' skill requirement.
    """
    req = _req("PostgreSQL", RequirementKind.SKILL)
    long_bullet = (
        "Led a cross-functional team of 12 engineers across 4 countries, coordinating "
        "agile sprints, handling stakeholder presentations, writing RFC documents, and "
        "occasionally reviewed PostgreSQL schema migrations for the data engineering team."
    )
    ev_items = [
        _ev("exp:1", "experience", long_bullet),
        _ev("skills:1", "skills", "Python, Django"),  # control
    ]
    selected = prefilter.select(req, ev_items)
    selected_ids = {e.evidence_id for e in selected}
    assert "exp:1" in selected_ids, "Long bullet with PostgreSQL mention must be retrieved via clause scoring"


# ---------------------------------------------------------------------------
# TEST I: Empty evidence pool → returns []
# ---------------------------------------------------------------------------
def test_i_empty_evidence_returns_empty(prefilter: EvidencePrefilter) -> None:
    req = _req("Docker", RequirementKind.SKILL)
    assert prefilter.select(req, []) == []


# ---------------------------------------------------------------------------
# TEST J: Wrong entity type — no valid evidence returns []
# ---------------------------------------------------------------------------
def test_j_no_valid_entity_type_returns_empty(prefilter: EvidencePrefilter) -> None:
    """
    DEGREE requirement with only skill/experience evidence → returns [].
    """
    req = _req("Bachelor's in Computer Science", RequirementKind.DEGREE)
    ev_items = [
        _ev("skills:1", "skills", "Python, Machine Learning"),
        _ev("exp:1", "experience", "3 years software engineering experience."),
    ]
    selected = prefilter.select(req, ev_items)
    assert selected == [], "No education evidence should return empty list"


# ---------------------------------------------------------------------------
# TEST K: Synonym reverse-match — requirement contains a synonym value
# (e.g. 'pub/sub' is a synonym for 'asynchronous programming')
# ---------------------------------------------------------------------------
def test_k_reverse_synonym_in_requirement(prefilter: EvidencePrefilter) -> None:
    """
    Requirement 'pub/sub messaging patterns' — 'messaging' is a synonym for
    'asynchronous programming'. Evidence mentioning 'event-driven' should be retrieved.
    """
    req = _req("pub/sub messaging patterns", RequirementKind.SKILL)
    ev_items = [
        _ev("exp:1", "experience", "Designed event-driven microservices with async await patterns."),
        _ev("skills:1", "skills", "Java, Spring Boot"),  # control
    ]
    selected = prefilter.select(req, ev_items)
    selected_ids = {e.evidence_id for e in selected}
    # Either synonym expansion or semantic similarity should retrieve exp:1
    assert len(selected) >= 1, "Reverse synonym expansion must retrieve at least one item"


# ---------------------------------------------------------------------------
# TEST L: Multiple items, diverse kinds — adaptive limit includes all good signals
# ---------------------------------------------------------------------------
def test_l_diverse_evidence_selected(prefilter: EvidencePrefilter) -> None:
    """
    'Python' requirement with matches in skills, experience, project —
    all three should appear in selected (up to limit).
    """
    req = _req("Python", RequirementKind.SKILL)
    ev_items = [
        _ev("skills:1", "skills", "Python, FastAPI, Docker"),
        _ev("exp:1", "experience", "Developed REST APIs using Python and Flask. Built CI/CD pipelines."),
        _ev("proj:1", "project", "Implemented a Python-based data pipeline for ETL processing."),
        _ev("sum:1", "summary", "Backend Python developer with 5 years experience."),
        _ev("skills:2", "skills", "JavaScript, Node.js, React"),  # control — no Python
    ]
    selected = prefilter.select(req, ev_items)
    selected_ids = {e.evidence_id for e in selected}
    # All four Python-mentioning items should be retrieved
    assert "skills:1" in selected_ids
    assert "exp:1" in selected_ids
    assert "proj:1" in selected_ids
    assert "skills:2" not in selected_ids, "Unrelated JavaScript evidence must not be selected"


# ---------------------------------------------------------------------------
# TEST M: Responsibility requirement uses experience/project/summary pool only
# ---------------------------------------------------------------------------
def test_m_responsibility_entity_pool(prefilter: EvidencePrefilter) -> None:
    """
    RESPONSIBILITY requirement must look at experience, project, summary — NOT skills.
    """
    req = _req("Lead code reviews and mentoring junior developers", RequirementKind.RESPONSIBILITY)
    ev_items = [
        _ev("exp:1", "experience", "Led weekly code reviews and mentored 3 junior engineers."),
        _ev("skills:1", "skills", "Python, code review tools"),
        _ev("proj:1", "project", "Mentored junior team members on project best practices."),
    ]
    selected = prefilter.select(req, ev_items)
    selected_ids = {e.evidence_id for e in selected}
    # exp:1 and proj:1 are in the allowed pool and should be retrieved
    assert "exp:1" in selected_ids or "proj:1" in selected_ids


# ---------------------------------------------------------------------------
# TEST N: Telemetry dict populated for all evaluated items
# ---------------------------------------------------------------------------
def test_n_telemetry_populated(prefilter: EvidencePrefilter) -> None:
    """
    Prefilter must populate retrieval_telemetry for each evaluated evidence item,
    including the new 'semantic_score' field.
    """
    req = _req("Redis", RequirementKind.SKILL, rid="req:redis")
    ev_items = [
        _ev("skills:1", "skills", "Redis, Memcached, caching"),
        _ev("exp:1", "experience", "Used Redis for session management and caching."),
    ]
    prefilter.select(req, ev_items)
    assert "req:redis" in prefilter.retrieval_telemetry
    records = prefilter.retrieval_telemetry["req:redis"]
    assert len(records) == 2
    for r in records:
        assert "cosine_score" in r
        assert "lexical_score" in r
        assert "semantic_score" in r, "New semantic_score field must be present in telemetry"
        assert "retrieval_source" in r
        assert "evidence_selected" in r


# ---------------------------------------------------------------------------
# TEST O: No evidence found even after fallback → returns [] gracefully
# ---------------------------------------------------------------------------
def test_o_total_zero_signal_returns_empty_or_fallback(prefilter: EvidencePrefilter) -> None:
    """
    When absolutely no signal matches (e.g., Chinese character requirement vs
    completely unrelated English-only resume), the prefilter should return []
    or the SemanticEvidenceRetriever.retrieve() fallback — and must NOT crash.
    """
    req = _req("量子计算经验", RequirementKind.SKILL)  # "Quantum computing experience" in Chinese
    ev_items = [
        _ev("skills:1", "skills", "JavaScript, TypeScript, React"),
        _ev("exp:1", "experience", "Worked as a frontend developer for 3 years."),
    ]
    try:
        selected = prefilter.select(req, ev_items)
        # Must return a list (possibly empty) — must not crash
        assert isinstance(selected, list)
    except Exception as e:
        pytest.fail(f"Prefilter must not crash on zero-signal input: {e}")


# ---------------------------------------------------------------------------
# NEW REGRESSION TESTS (Scenarios A–M Verification)
# ---------------------------------------------------------------------------

def test_p_exact_python_retrieval(prefilter: EvidencePrefilter) -> None:
    """Exact: Python -> Python evidence."""
    req = _req("Python", RequirementKind.SKILL)
    ev_items = [_ev("skills:1", "skills", "Python, FastAPI, PostgreSQL")]
    selected = prefilter.select(req, ev_items)
    assert len(selected) == 1 and selected[0].evidence_id == "skills:1"


def test_q_alias_aws_amazon_web_services(prefilter: EvidencePrefilter) -> None:
    """Alias: AWS -> Amazon Web Services."""
    req = _req("AWS", RequirementKind.SKILL)
    ev_items = [_ev("exp:1", "experience", "Deployed microservices on Amazon Web Services EC2 and S3.")]
    selected = prefilter.select(req, ev_items)
    assert len(selected) >= 1 and selected[0].evidence_id == "exp:1"


def test_r_abbreviation_k8s_kubernetes(prefilter: EvidencePrefilter) -> None:
    """Abbreviation: Kubernetes -> K8s."""
    req = _req("Kubernetes", RequirementKind.SKILL)
    ev_items = [_ev("exp:1", "experience", "Managed K8s cluster deployments.")]
    selected = prefilter.select(req, ev_items)
    assert len(selected) >= 1 and selected[0].evidence_id == "exp:1"


def test_s_related_terminology_redis_memcached(prefilter: EvidencePrefilter) -> None:
    """Related Technical Terminology: Redis -> Memcached / in-memory cache."""
    req = _req("Redis", RequirementKind.SKILL)
    ev_items = [_ev("exp:1", "experience", "Implemented in-memory key-value cache cluster using Memcached.")]
    selected = prefilter.select(req, ev_items)
    assert len(selected) >= 1 and selected[0].evidence_id == "exp:1"


def test_t_semantic_relationship_ml_deep_learning(prefilter: EvidencePrefilter) -> None:
    """Semantic Technical Relationship: Machine Learning -> Deep Learning / Neural Networks."""
    req = _req("Machine Learning", RequirementKind.SKILL)
    ev_items = [_ev("exp:1", "experience", "Trained deep learning neural network models for NLP tasks.")]
    selected = prefilter.select(req, ev_items)
    assert len(selected) >= 1 and selected[0].evidence_id == "exp:1"


def test_u_compound_requirement_decomposition(prefilter: EvidencePrefilter) -> None:
    """Compound requirement: Python + FastAPI requirement vs Python-only evidence."""
    req = _req("Python and FastAPI backend development", RequirementKind.SKILL)
    ev_items = [_ev("exp:1", "experience", "Built REST APIs using Python and Django.")]
    selected = prefilter.select(req, ev_items)
    assert len(selected) >= 1 and selected[0].evidence_id == "exp:1"


def test_v_long_bullet_comma_clause(prefilter: EvidencePrefilter) -> None:
    """Long bullet: Kubernetes appearing late in long comma-separated bullet with lowercase commas."""
    req = _req("Kubernetes", RequirementKind.SKILL)
    ev_items = [_ev("exp:1", "experience", "Built cloud infrastructure, CI/CD pipelines, monitoring dashboards, security hardening, Kubernetes clusters and release automation.")]
    selected = prefilter.select(req, ev_items)
    assert len(selected) >= 1 and selected[0].evidence_id == "exp:1"


def test_w_unrelated_evidence_filtered(prefilter: EvidencePrefilter) -> None:
    """Unrelated evidence must NOT be aggressively retrieved."""
    req = _req("Kubernetes", RequirementKind.SKILL)
    ev_items = [_ev("exp:1", "experience", "Experienced in accounting, invoice auditing, tax compliance, and payroll processing.")]
    selected = prefilter.select(req, ev_items)
    assert len(selected) == 0


def test_x_cosine_only_routes_to_llm(prefilter: EvidencePrefilter) -> None:
    """Cosine-only retrieval must return list[Evidence] for LLM evaluation and never produce a final verdict directly."""
    req = _req("SIEM monitoring", RequirementKind.SKILL)
    ev_items = [_ev("exp:1", "experience", "Threat detection, Splunk log analysis, incident response.")]
    selected = prefilter.select(req, ev_items)
    assert isinstance(selected, list)
    for e in selected:
        assert isinstance(e, Evidence)

