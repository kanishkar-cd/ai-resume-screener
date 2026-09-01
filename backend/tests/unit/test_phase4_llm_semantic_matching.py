import pytest
from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, Requirement, RequirementKind,
)
from app.services.matching_service import GroqMatchEvaluator


@pytest.fixture
def evaluator() -> GroqMatchEvaluator:
    GroqMatchEvaluator._cache.clear()
    return GroqMatchEvaluator()


def test_1_exact_skill_match(evaluator: GroqMatchEvaluator) -> None:
    """1. Exact skill match -> MATCHED."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React.js")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="React.js")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=1.0, evidence_ids=["skills:1"], reasoning="Exact skill match for React.js")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert val[0].evidence_ids == ["skills:1"]


def test_2_equivalent_wording(evaluator: GroqMatchEvaluator) -> None:
    """2. Equivalent wording -> MATCHED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Developed backend API endpoints using FastAPI")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["project:1"], reasoning="Backend API endpoints is equivalent to Build REST APIs")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert val[0].evidence_ids == ["project:1"]


def test_3_project_implementation_demonstrates_capability(evaluator: GroqMatchEvaluator) -> None:
    """3. Project implementation demonstrates JD capability -> MATCHED."""
    reqs = [Requirement(requirement_id="project_relevance:1", kind=RequirementKind.PROJECT_RELEVANCE, text="Build and maintain REST APIs using Node.js")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="E-Commerce API: Developed backend API endpoints with Node.js")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="project_relevance:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["project:1"], reasoning="Project implementation demonstrates Node.js REST API development")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert val[0].evidence_ids == ["project:1"]


def test_4_internship_demonstrates_responsibility(evaluator: GroqMatchEvaluator) -> None:
    """4. Internship demonstrates responsibility -> MATCHED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build data pipelines")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Data Engineering Intern: Built scalable ETL pipelines using PySpark")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["experience:1"], reasoning="Internship work explicitly built ETL data pipelines")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert val[0].evidence_ids == ["experience:1"]


def test_5_skills_only_responsibility(evaluator: GroqMatchEvaluator) -> None:
    """5. Skills-only evidence for responsibility -> NOT MATCHED (UNRESOLVED / NO_MATCH)."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Design and integrate MongoDB databases with Node.js applications")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="MongoDB")]
    # Prefilter excludes skills:1 for responsibility -> allowed_evidence is empty for skills:1
    allowed_evidence = {"responsibility:1": set()}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.UNRESOLVED, confidence=0.5, evidence_ids=[], reasoning="Merely listing MongoDB in skills does not demonstrate integration responsibility")
    ])
    val = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert val[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_6_compound_requirement_most_concepts_demonstrated(evaluator: GroqMatchEvaluator) -> None:
    """6. Compound requirement with most concepts demonstrated -> PARTIALLY_MATCHED / MATCHED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build and maintain REST APIs using Node.js and Express.js")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using Node.js")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.PARTIALLY_MATCHED, confidence=0.85, evidence_ids=["project:1"], reasoning="Demonstrated Node.js REST APIs but Express.js is omitted")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.PARTIALLY_MATCHED
    assert val[0].evidence_ids == ["project:1"]


def test_7_unrelated_technology(evaluator: GroqMatchEvaluator) -> None:
    """7. Unrelated technology -> NOT MATCHED (NO_MATCH / UNRESOLVED)."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React.js")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Angular")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="Angular is a distinct frontend framework from React.js")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_8_partial_responsibility(evaluator: GroqMatchEvaluator) -> None:
    """8. Partial responsibility -> PARTIALLY_MATCHED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Develop frontend UI and automate end-to-end tests")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Developed frontend user interfaces using React")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.PARTIALLY_MATCHED, confidence=0.8, evidence_ids=["project:1"], reasoning="Frontend UI developed, but automated e2e testing is absent")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.PARTIALLY_MATCHED
    assert val[0].evidence_ids == ["project:1"]


def test_9_ambiguous_evidence(evaluator: GroqMatchEvaluator) -> None:
    """9. Ambiguous evidence -> UNRESOLVED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Implement Basic Authentication security headers")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Added login page")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.UNRESOLVED, confidence=0.5, evidence_ids=[], reasoning="Generic login page is ambiguous for HTTP Basic Authentication security headers")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.UNRESOLVED


def test_10_no_evidence(evaluator: GroqMatchEvaluator) -> None:
    """10. No evidence -> NO_MATCH."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Kubernetes")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Python, SQL")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="No evidence found for Kubernetes")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_11_responsive_ui_semantic_match(evaluator: GroqMatchEvaluator) -> None:
    """11. Responsive UI semantic match."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="responsive web interfaces")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Implemented responsive React user interfaces")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["project:1"], reasoning="Responsive React user interfaces matches responsive web interfaces")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED


def test_12_rest_api_semantic_match(evaluator: GroqMatchEvaluator) -> None:
    """12. REST API semantic match."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Developed backend API endpoints using Express.js")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["project:1"], reasoning="Developed backend API endpoints is a semantic match for Build REST APIs")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED


def test_13_debugging_semantic_match(evaluator: GroqMatchEvaluator) -> None:
    """13. Debugging semantic match."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="debugging and troubleshooting")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Identified root causes and fixed application issues")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["experience:1"], reasoning="Identified root causes and fixed issues matches debugging and troubleshooting")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED


def test_14_documentation_semantic_match(evaluator: GroqMatchEvaluator) -> None:
    """14. Documentation semantic match."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Document data workflows")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Created documentation for ETL processes")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["project:1"], reasoning="Created documentation for ETL processes satisfies Document data workflows")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED


def test_15_mongodb_vs_postgresql_distinct(evaluator: GroqMatchEvaluator) -> None:
    """15. MongoDB vs PostgreSQL remains distinct."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="MongoDB")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="PostgreSQL")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="PostgreSQL is a relational database and distinct from MongoDB document store")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_16_react_vs_angular_distinct(evaluator: GroqMatchEvaluator) -> None:
    """16. React vs Angular remains distinct."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Angular")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="Angular is a separate framework from React")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_17_docker_usage_not_automatically_deployment_evidence(evaluator: GroqMatchEvaluator) -> None:
    """17. Docker usage is not automatically deployment evidence."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Deploy applications using Docker to AWS ECS")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Docker")]
    allowed_evidence = {"responsibility:1": set()}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.UNRESOLVED, confidence=0.5, evidence_ids=[], reasoning="Listing Docker skill alone does not prove deployment to AWS ECS")
    ])
    val = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert val[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_18_stakeholder_collaboration_not_inferred_from_developer_collaboration(evaluator: GroqMatchEvaluator) -> None:
    """18. Stakeholder collaboration is not inferred from developer collaboration alone."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Collaborate with developers and business stakeholders")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Worked closely with software developers in an Agile team")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.PARTIALLY_MATCHED, confidence=0.85, evidence_ids=["experience:1"], reasoning="Developer collaboration is shown, but business stakeholder collaboration is unmentioned")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.PARTIALLY_MATCHED


def test_19_every_positive_verdict_cites_supplied_evidence_ids(evaluator: GroqMatchEvaluator) -> None:
    """19. Every positive verdict cites supplied evidence IDs."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using FastAPI")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["project:1"], reasoning="Cites valid project:1")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert len(val[0].evidence_ids) > 0
    assert val[0].evidence_ids == ["project:1"]
