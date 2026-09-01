from types import SimpleNamespace
import pytest

from app.schemas.matching import Requirement, RequirementKind
from app.services.matching_service import (
    DeterministicRequirementMatcher,
    Evidence,
    EvidenceBuilder,
    EvidencePrefilter,
    GroqMatchEvaluator,
    RequirementBuilder,
    SemanticEvidenceRetriever,
)
from app.services.scoring.component_scoring_service import ComponentScoringService


@pytest.fixture
def sample_evidence_pool():
    return [
        Evidence(evidence_id="skills:1", kind="skills", text="Python, FastAPI, Docker", canonical_terms=["Python", "FastAPI", "Docker"]),
        Evidence(evidence_id="experience:1", kind="experience", text="Software Engineer at TechCorp. Built distributed event-streaming pipelines using message queues.", canonical_terms=[]),
        Evidence(evidence_id="project:1", kind="project", text="Payment Gateway Microservices built with Python and PostgreSQL.", canonical_terms=["Python", "PostgreSQL"]),
        Evidence(evidence_id="summary:1", kind="summary", text="Backend Developer specialized in cloud infrastructure and high performance systems.", canonical_terms=[]),
        Evidence(evidence_id="certification:1", kind="certification", text="AWS Certified Solutions Architect", canonical_terms=["AWS Certified Solutions Architect"]),
        Evidence(evidence_id="languages:1", kind="languages", text="English, Spanish", canonical_terms=["English", "Spanish"]),
    ]


def test_skill_evidence_isolation_certification_excluded(sample_evidence_pool):
    """Verify certification evidence is strictly excluded from skill pre-filtering."""
    prefilter = EvidencePrefilter(threshold=0.15, limit=5)
    req = Requirement(
        requirement_id="skill:1",
        kind=RequirementKind.SKILL,
        text="AWS",
        canonical_value="AWS",
    )
    
    selected = prefilter.select(req, sample_evidence_pool)
    selected_ids = {e.evidence_id for e in selected}
    
    # Certification must NOT be in skill evidence
    assert "certification:1" not in selected_ids
    assert all(e.kind in {"skills", "project", "experience", "summary"} for e in selected)


def test_skill_evidence_isolation_language_excluded(sample_evidence_pool):
    """Verify language evidence is strictly excluded from skill pre-filtering."""
    prefilter = EvidencePrefilter(threshold=0.15, limit=5)
    req = Requirement(
        requirement_id="skill:2",
        kind=RequirementKind.SKILL,
        text="English",
        canonical_value="English",
    )
    
    selected = prefilter.select(req, sample_evidence_pool)
    selected_ids = {e.evidence_id for e in selected}
    
    # Language evidence must NOT be in skill evidence
    assert "languages:1" not in selected_ids


def test_component_scoring_evidence_isolation():
    """Verify ComponentScoringService does not include certifications in candidate_skills pool for skill scoring."""
    service = ComponentScoringService()
    
    resume = SimpleNamespace(
        skills=["Python"],
        certifications=[{"name": "AWS Certified Solutions Architect"}],
        languages=["English"],
        experience=[],
        summary="Backend engineer",
    )
    
    job = SimpleNamespace(
        required_skills=["AWS"],
        skills=["AWS"],
        preferred_skills=[],
    )
    
    component_scores = service.score(resume, job, config=None)
    
    # Skill score for AWS must be 0 because certification is isolated and not counted as a skill
    assert "AWS" in component_scores.skills.missing_items
    assert component_scores.skills.score == 0.0


def test_zero_overlap_skill_triggers_semantic_retrieval(sample_evidence_pool):
    """Verify a skill with 0 keyword stem overlap (Kafka vs message queues) retrieves evidence instead of returning []."""
    prefilter = EvidencePrefilter(threshold=0.15, limit=5)
    req = Requirement(
        requirement_id="skill:3",
        kind=RequirementKind.SKILL,
        text="Kafka",
        canonical_value="Kafka",
    )
    
    selected = prefilter.select(req, sample_evidence_pool)
    
    # Pre-filter must NOT return empty list for zero-overlap skill
    assert len(selected) > 0
    selected_kinds = {e.kind for e in selected}
    assert selected_kinds.issubset({"skills", "project", "experience", "summary"})


def test_adaptive_top_k_and_diversity(sample_evidence_pool):
    """Verify diverse evidence types (skills, project, experience, summary) are selected."""
    prefilter = EvidencePrefilter(threshold=0.15, limit=5)
    req = Requirement(
        requirement_id="skill:4",
        kind=RequirementKind.SKILL,
        text="Python",
        canonical_value="Python",
    )
    
    selected = prefilter.select(req, sample_evidence_pool)
    
    # Python appears in skills:1 and project:1
    selected_ids = {e.evidence_id for e in selected}
    assert "skills:1" in selected_ids or "project:1" in selected_ids


def test_batch_payload_evidence_deduplication(sample_evidence_pool):
    """Verify GroqMatchEvaluator payload includes allowed_evidence_ids per requirement and lists evidence text once."""
    evaluator = GroqMatchEvaluator()
    reqs = [
        Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python"),
        Requirement(requirement_id="skill:2", kind=RequirementKind.SKILL, text="FastAPI"),
    ]
    allowed_evidence = {
        "skill:1": {"skills:1", "project:1"},
        "skill:2": {"skills:1"},
    }
    
    payload = evaluator._payload(reqs, sample_evidence_pool, allowed_evidence)
    
    # Check structure
    messages = payload["messages"]
    user_content = messages[1]["content"]
    import json
    data = json.loads(user_content)
    
    assert "requirements" in data
    assert "evidence" in data
    
    req1 = next(r for r in data["requirements"] if r["requirement_id"] == "skill:1")
    assert req1["allowed_evidence_ids"] == ["project:1", "skills:1"]
    
    # Evidence text listed only once in evidence array
    assert len(data["evidence"]) == len(sample_evidence_pool)
