import pytest
from types import SimpleNamespace

from app.schemas.matching import (
    Evidence, EvidenceStrength, MatchMethod, MatchStatus, MatchVerdict,
    Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder,
    SemanticEvidenceRetriever, classify_evidence_strength,
    detect_contradiction, try_semantic_direct_match,
)
from app.services.pipeline.canonical_dictionaries import CONTROLLED_CONCEPT_EQUIVALENCES


# ============================================================================
# 1. FALSE POSITIVE PREVENTION TESTS (Section 20 & 6)
# ============================================================================

def test_docker_vs_kubernetes_not_matched():
    """Docker and Kubernetes are related technologies, NOT equivalents. Must NOT match."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Docker")
    resume = SimpleNamespace(skills=["Kubernetes"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Kubernetes", canonical_terms=["Kubernetes"])]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status != MatchStatus.MATCHED

    # Also verify contradiction gate blocks direct cosine match
    contra, reason = detect_contradiction("Docker", "Kubernetes cluster management")
    assert contra is True
    assert "Distinct technology mismatch" in reason

    direct_match = try_semantic_direct_match(req, evidence)
    assert direct_match is None


def test_java_vs_javascript_not_matched():
    """Java and JavaScript are distinct languages. Must NOT match."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Java")
    resume = SimpleNamespace(skills=["JavaScript"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="JavaScript", canonical_terms=["JavaScript"])]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status != MatchStatus.MATCHED

    contra, reason = detect_contradiction("Java", "JavaScript frontend development")
    assert contra is True
    assert "Distinct technology mismatch" in reason

    direct_match = try_semantic_direct_match(req, evidence)
    assert direct_match is None


def test_aws_mention_vs_aws_certification_not_matched():
    """AWS mention must not satisfy AWS Certified Solutions Architect certification."""
    req = Requirement(
        requirement_id="cert:1",
        kind=RequirementKind.CERTIFICATION,
        text="AWS Certified Solutions Architect",
    )
    resume = SimpleNamespace(certifications=[], skills=["AWS"], experience=[{"description": "Built app on AWS"}])
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Built web application using AWS S3 and EC2")]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.NO_MATCH

    # Cosine direct match must be prohibited on certification requirements
    direct_match = try_semantic_direct_match(req, evidence)
    assert direct_match is None


def test_learning_python_vs_critical_python_not_matched():
    """'Learning Python' must not satisfy a critical Python requirement via direct cosine match."""
    req = Requirement(
        requirement_id="skill:1",
        kind=RequirementKind.SKILL,
        text="Python",
        importance="critical",
        hard_constraint=True,
    )
    ev = Evidence(
        evidence_id="exp:1",
        kind="experience",
        text="Currently learning Python and beginner concepts",
        evidence_strength=EvidenceStrength.TRAINING,
    )

    contra, reason = detect_contradiction(req.text, ev.text)
    assert contra is True
    assert "Early learner" in reason

    direct_match = try_semantic_direct_match(req, [ev])
    assert direct_match is None


def test_coursework_alone_cannot_direct_match_critical_skill():
    """An introductory course must NOT directly match a critical production skill."""
    req = Requirement(
        requirement_id="skill:1",
        kind=RequirementKind.SKILL,
        text="Machine Learning",
        importance="critical",
        hard_constraint=True,
    )
    ev = Evidence(
        evidence_id="course:1",
        kind="project",
        text="Completed an introductory machine learning course on Coursera",
        evidence_strength=EvidenceStrength.COURSE,
    )

    # Classification test
    strength = classify_evidence_strength(ev.text, ev.kind)
    assert strength == EvidenceStrength.COURSE

    # Gate blocks direct cosine match for critical skill
    direct_match = try_semantic_direct_match(req, [ev])
    assert direct_match is None


def test_bachelors_vs_masters_degree_structured_matching():
    """Education/degree must use structured evaluation, NEVER cosine direct match."""
    req = Requirement(requirement_id="deg:1", kind=RequirementKind.DEGREE, text="Master's Degree in Computer Science")
    evidence = [Evidence(evidence_id="edu:1", kind="education", text="Bachelor of Science in Computer Science")]

    # Cosine direct match forbidden on degree
    direct_match = try_semantic_direct_match(req, evidence)
    assert direct_match is None


def test_explicit_negative_experience_rejected():
    """'No experience with Java' must NOT produce a match."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Java")
    ev = Evidence(evidence_id="exp:1", kind="experience", text="Strong backend developer with Python, but no experience with Java.")

    contra, reason = detect_contradiction(req.text, ev.text)
    assert contra is True
    assert "Explicit negative statement detected" in reason

    direct_match = try_semantic_direct_match(req, [ev])
    assert direct_match is None


# ============================================================================
# 2. FALSE NEGATIVE FLEXIBILITY TESTS (Section 21 & 7)
# ============================================================================

def test_reactjs_equivalent_to_react():
    """React.js and React are equivalent concepts. Must MATCH with method=CONCEPT or ALIAS."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React.js")
    resume = SimpleNamespace(skills=["React"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="React", canonical_terms=["React"])]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.method in {MatchMethod.CONCEPT, MatchMethod.ALIAS, MatchMethod.EXACT}


def test_postgresql_database_equivalent_to_postgresql():
    """'PostgreSQL database' and 'PostgreSQL' are equivalent concepts."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="PostgreSQL database")
    resume = SimpleNamespace(skills=["PostgreSQL"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="PostgreSQL", canonical_terms=["PostgreSQL"])]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.method in {MatchMethod.CONCEPT, MatchMethod.ALIAS}


def test_restful_api_equivalent_to_rest_api():
    """'RESTful API development' and 'REST API' are equivalent concepts."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="RESTful API development")
    resume = SimpleNamespace(skills=["REST API"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="REST API", canonical_terms=["REST API"])]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.method in {MatchMethod.CONCEPT, MatchMethod.ALIAS}


def test_javascript_and_js_equivalent():
    """'JavaScript' and 'JS' are equivalent concepts."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="JavaScript")
    resume = SimpleNamespace(skills=["JS"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="JS", canonical_terms=["JS"])]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_kubernetes_orchestration_equivalent():
    """'Kubernetes orchestration' matches 'Kubernetes'."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Kubernetes orchestration")
    resume = SimpleNamespace(skills=["Kubernetes"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Kubernetes", canonical_terms=["Kubernetes"])]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.method in {MatchMethod.CONCEPT, MatchMethod.ALIAS}


def test_python_backend_development_equivalent():
    """'Python backend development' matches candidate with 'Python'."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python backend development")
    resume = SimpleNamespace(skills=["Python"], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Python", canonical_terms=["Python"])]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.method in {MatchMethod.CONCEPT, MatchMethod.ALIAS}


# ============================================================================
# 3. STRUCTURED FACTUAL PARTIAL MATCHING TESTS (Section 8)
# ============================================================================

def test_experience_partial_matching_proportional():
    """Candidate with 3 years (36 months) against 5 years (60 months) requirement returns PARTIALLY_MATCHED with coverage=0.60."""
    req = Requirement(requirement_id="exp:1", kind=RequirementKind.EXPERIENCE, text="5+ years of experience")
    resume = SimpleNamespace(
        experience=[
            {"duration_months": 36, "title": "Software Engineer", "company": "Tech Corp"}
        ]
    )
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Software Engineer at Tech Corp (36 months)")]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)

    assert verdict.status == MatchStatus.PARTIALLY_MATCHED
    assert verdict.coverage == 0.60
    assert verdict.coverage_score == 0.60
    assert "partially meets" in verdict.reasoning


def test_composite_skill_partial_matching():
    """Composite skill: 'React and TypeScript and Redux'. Candidate has React and TypeScript. Must return PARTIALLY_MATCHED."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React and TypeScript and Redux")
    resume = SimpleNamespace(skills=["React", "TypeScript"], experience=[])
    evidence = [
        Evidence(evidence_id="skills:1", kind="skills", text="React, TypeScript", canonical_terms=["React", "TypeScript"])
    ]

    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)

    assert verdict.status == MatchStatus.PARTIALLY_MATCHED
    assert verdict.coverage == pytest.approx(0.67, abs=0.01)
    assert verdict.coverage_score == pytest.approx(0.67, abs=0.01)
    assert "React" in verdict.matched_concepts
    assert "TypeScript" in verdict.matched_concepts
    assert "Redux" in verdict.missing_concepts


# ============================================================================
# 4. EVIDENCE STRENGTH CLASSIFICATION (Section 10)
# ============================================================================

def test_classify_evidence_strength_categories():
    """Verify evidence strength properly categorizes different contextual signals."""
    # Ownership
    assert classify_evidence_strength("Architected and led production cloud infrastructure", "experience") == EvidenceStrength.OWNERSHIP
    # Professional use
    assert classify_evidence_strength("Built and deployed microservices in production using Python", "experience") == EvidenceStrength.PROFESSIONAL_USE
    # Project
    assert classify_evidence_strength("Built fullstack portfolio project using Next.js", "project") == EvidenceStrength.PROJECT
    # Course
    assert classify_evidence_strength("Completed an introductory course on machine learning on Coursera", "project") == EvidenceStrength.COURSE
    # Training
    assert classify_evidence_strength("Attended 3-month fullstack coding bootcamp training", "experience") == EvidenceStrength.TRAINING
    # Mention only
    assert classify_evidence_strength("Python, SQL, Git", "skills") == EvidenceStrength.MENTION_ONLY


# ============================================================================
# 5. HIGH CONFIDENCE COSINE DIRECT MATCH PASSES WITH SAFE EVIDENCE (Section 5, 9)
# ============================================================================

def test_cosine_retrieves_evidence_for_llm_evaluation_not_direct_match():
    """Cosine similarity retrieves candidate evidence, but alone cannot produce direct match."""
    req = Requirement(
        requirement_id="skill:1",
        kind=RequirementKind.SKILL,
        text="Apache Kafka streaming",
        importance="important",
    )
    ev = Evidence(
        evidence_id="exp:1",
        kind="experience",
        text="Apache Kafka event streaming platform",
        evidence_strength=EvidenceStrength.PROFESSIONAL_USE,
    )

    sim = SemanticEvidenceRetriever.cosine_similarity(req.text, ev.text)
    assert sim >= 0.85

    # Cosine alone cannot decide MATCHED
    verdict = try_semantic_direct_match(req, [ev], threshold=0.85)
    assert verdict is None, "Cosine must never directly decide MATCHED without LLM evaluation"

