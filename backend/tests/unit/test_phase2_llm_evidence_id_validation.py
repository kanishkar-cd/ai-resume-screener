import pytest
from types import SimpleNamespace
from app.schemas.matching import (
    Evidence, LLMVerdict, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    GroqMatchEvaluator, HybridMatchingService,
)
LLMVerdictItem = LLMVerdict


@pytest.fixture
def evaluator() -> GroqMatchEvaluator:
    return GroqMatchEvaluator()


def test_1_matched_valid_project_evidence_remains_matched(evaluator: GroqMatchEvaluator) -> None:
    """1. MATCHED + valid project:1 -> remains MATCHED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build ETL pipelines")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built Spark ETL pipeline")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["project:1"], reasoning="Project satisfies ETL pipeline")
    ])
    validated = evaluator._validate(batch, reqs, evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert validated[0].evidence_ids == ["project:1"]


def test_2_matched_valid_experience_evidence_remains_matched(evaluator: GroqMatchEvaluator) -> None:
    """2. MATCHED + valid experience:1 -> remains MATCHED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build ETL pipelines")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Data Engineering Intern - Built ETL pipelines")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["experience:1"], reasoning="Internship demonstrates ETL pipelines")
    ])
    validated = evaluator._validate(batch, reqs, evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert validated[0].evidence_ids == ["experience:1"]


def test_3_matched_multiple_valid_evidence_ids_remains_matched(evaluator: GroqMatchEvaluator) -> None:
    """3. MATCHED + multiple valid evidence IDs -> remains MATCHED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build ETL pipelines")]
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Built Spark ETL pipeline"),
        Evidence(evidence_id="experience:1", kind="experience", text="Data Engineering Intern - Built ETL pipelines"),
    ]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["project:1", "experience:1"], reasoning="Both project and experience demonstrate ETL")
    ])
    validated = evaluator._validate(batch, reqs, evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert set(validated[0].evidence_ids) == {"project:1", "experience:1"}


def test_4_matched_hallucinated_evidence_id_rejected(evaluator: GroqMatchEvaluator) -> None:
    """4. MATCHED + hallucinated evidence ID -> hallucinated ID rejected, verdict demoted to UNRESOLVED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build ETL pipelines")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built Spark ETL pipeline")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["fake:99"], reasoning="Hallucinated ID cited")
    ])
    validated = evaluator._validate(batch, reqs, evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.UNRESOLVED
    assert validated[0].method == MatchMethod.LLM_UNRESOLVED
    assert validated[0].evidence_ids == []


def test_5_matched_valid_and_invalid_ids_retains_valid(evaluator: GroqMatchEvaluator) -> None:
    """5. MATCHED + valid and invalid IDs -> valid IDs retained, invalid removed."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build ETL pipelines")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built Spark ETL pipeline")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["project:1", "fake:99"], reasoning="Mixed valid and invalid evidence IDs")
    ])
    validated = evaluator._validate(batch, reqs, evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert validated[0].evidence_ids == ["project:1"]


def test_6_matched_no_evidence_ids_single_supplied_safe_association(evaluator: GroqMatchEvaluator) -> None:
    """6. MATCHED + no evidence IDs + exactly one supplied evidence -> safe association."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build ETL pipelines")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built Spark ETL pipeline")]
    allowed_evidence = {"responsibility:1": {"project:1"}}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=[], reasoning="Candidate demonstrated ETL pipeline")
    ])
    validated = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert validated[0].evidence_ids == ["project:1"]


def test_7_matched_no_evidence_ids_multiple_supplied_unresolved(evaluator: GroqMatchEvaluator) -> None:
    """7. MATCHED + no evidence IDs + multiple supplied evidence -> UNRESOLVED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build ETL pipelines")]
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Built Spark ETL pipeline"),
        Evidence(evidence_id="experience:1", kind="experience", text="Data Engineering Intern"),
    ]
    allowed_evidence = {"responsibility:1": {"project:1", "experience:1"}}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=[], reasoning="Candidate demonstrated ETL pipeline")
    ])
    validated = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.UNRESOLVED
    assert validated[0].method == MatchMethod.LLM_UNRESOLVED
    assert validated[0].evidence_ids == []


def test_8_partially_matched_valid_evidence_remains_partially_matched(evaluator: GroqMatchEvaluator) -> None:
    """8. PARTIALLY_MATCHED + valid evidence -> remains PARTIALLY_MATCHED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build ETL pipelines")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built partial ETL script")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="responsibility:1", status=MatchStatus.PARTIALLY_MATCHED, confidence=0.8, evidence_ids=["project:1"], reasoning="Partial ETL pipeline implementation")
    ])
    validated = evaluator._validate(batch, reqs, evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.PARTIALLY_MATCHED
    assert validated[0].method == MatchMethod.LLM_CONFIRMED
    assert validated[0].evidence_ids == ["project:1"]


def test_9_project_evidence_not_rejected_because_it_is_project(evaluator: GroqMatchEvaluator) -> None:
    """9. Project evidence is not rejected merely because it is project evidence."""
    reqs = [Requirement(requirement_id="project_relevance:1", kind=RequirementKind.PROJECT_RELEVANCE, text="Build REST APIs")]
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built FastAPI REST API")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="project_relevance:1", status=MatchStatus.MATCHED, confidence=0.95, evidence_ids=["project:1"], reasoning="Project demonstrates FastAPI REST API")
    ])
    validated = evaluator._validate(batch, reqs, evidence)
    assert len(validated) == 1
    assert validated[0].status == MatchStatus.MATCHED
    assert validated[0].evidence_ids == ["project:1"]


def test_10_skills_only_evidence_cannot_be_invented_as_project_evidence(evaluator: GroqMatchEvaluator) -> None:
    """10. Skills-only evidence cannot be invented as project evidence when not supplied for requirement."""
    reqs = [Requirement(requirement_id="project_relevance:1", kind=RequirementKind.PROJECT_RELEVANCE, text="Build REST APIs")]
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Built FastAPI REST API"),
        Evidence(evidence_id="skills:1", kind="skills", text="Python, SQL"),
    ]
    # Allowed evidence for project_relevance contains only project:1 (skills:1 is excluded by prefilter)
    allowed_evidence = {"project_relevance:1": {"project:1"}}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(requirement_id="project_relevance:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:1"], reasoning="Skills list contains Python")
    ])
    validated = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert len(validated) == 1
    # skills:1 is unsupplied for this requirement -> hallucinated/unsupplied citation rejected -> UNRESOLVED
    assert validated[0].status == MatchStatus.UNRESOLVED
    assert validated[0].evidence_ids == []


@pytest.mark.asyncio
async def test_11_hybrid_matching_service_preserves_valid_llm_verdict() -> None:
    """11. HybridMatchingService does not demote a valid LLM verdict unnecessarily."""
    job = SimpleNamespace(
        required_skills=["Python"],
        preferred_skills=[],
        responsibilities=["Perform vulnerability triage with Splunk SIEM and Snort NIDS."],
        degree_requirements=[],
        experience_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    resume = SimpleNamespace(
        skills=["Python"],
        projects=[{"name": "Security Monitoring Lab", "description": "Configured SIEM security alerts.", "technologies": ["Splunk"]}],
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )
    extracted = SimpleNamespace(
        skills=["Python"],
        projects=resume.projects,
        experience=[],
        education=[],
        certifications=[],
        languages=[],
    )

    class MockEvaluator:
        async def evaluate(self, requirements, evidence, allowed_evidence=None):
            return [MatchVerdict(
                requirement_id="responsibility:1",
                status=MatchStatus.MATCHED,
                confidence=0.9,
                evidence_ids=["project:1"],
                reasoning="Security monitoring project satisfies SIEM triage responsibility.",
                method=MatchMethod.LLM_CONFIRMED,
            )]

    hybrid = HybridMatchingService(evaluator=MockEvaluator())
    enriched, fused = await hybrid.match(job, resume, extracted, config=None)
    resp_verdict = next(v for v in fused if v.requirement_id == "responsibility:1")
    assert resp_verdict.status == MatchStatus.MATCHED
    assert resp_verdict.method == MatchMethod.LLM_CONFIRMED
    assert resp_verdict.evidence_ids == ["project:1"]


def test_12_existing_deterministic_matching_behavior_remains_unchanged() -> None:
    """12. Existing deterministic matching behavior remains unchanged."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python", canonical_value="Python", required=True)
    resume = SimpleNamespace(skills=["Python"])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Python", canonical_terms=["Python"])]
    matcher = HybridMatchingService().matcher
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.method == MatchMethod.EXACT
    assert verdict.evidence_ids == ["skills:1"]
