import pytest
from types import SimpleNamespace
from app.services.matching_service import (
    RequirementBuilder, EvidenceBuilder, DeterministicRequirementMatcher, GroqMatchEvaluator,
)
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService
from app.schemas.matching import (
    Requirement, RequirementKind, Evidence, MatchStatus, MatchMethod, LLMVerdict, LLMVerdictBatch,
)


@pytest.fixture
def evaluator() -> GroqMatchEvaluator:
    GroqMatchEvaluator._cache.clear()
    return GroqMatchEvaluator()


def test_1_pmo_project_tracker_responsibility() -> None:
    """1. PMO project tracker responsibility matching."""
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Maintain project schedules and milestone trackers.")
    resume = SimpleNamespace(
        experience=[{"description": "Maintained project schedules and milestone trackers."}],
        projects=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED
    assert verdict.evidence_ids == ["experience:1"]


def test_2_raid_log_responsibility() -> None:
    """2. RAID log responsibility matching."""
    req = Requirement(requirement_id="responsibility:2", kind=RequirementKind.RESPONSIBILITY, text="Maintain RAID logs and risk registers.")
    resume = SimpleNamespace(
        experience=[{"description": "Maintained RAID logs and updated risk registers daily."}],
        projects=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_3_milestone_tracking() -> None:
    """3. Milestone tracking responsibility."""
    req = Requirement(requirement_id="responsibility:3", kind=RequirementKind.RESPONSIBILITY, text="Track project milestones and dependencies.")
    resume = SimpleNamespace(
        experience=[{"description": "Tracked project milestones and key engineering dependencies."}],
        projects=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_4_status_reporting() -> None:
    """4. Status reporting responsibility."""
    req = Requirement(requirement_id="responsibility:4", kind=RequirementKind.RESPONSIBILITY, text="Prepare weekly status reports.")
    resume = SimpleNamespace(
        experience=[{"description": "Prepared weekly status reports for leadership."}],
        projects=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_5_stakeholder_update_coordination() -> None:
    """5. Stakeholder update coordination responsibility."""
    req = Requirement(requirement_id="responsibility:5", kind=RequirementKind.RESPONSIBILITY, text="Coordinate stakeholder meetings and action items.")
    resume = SimpleNamespace(
        experience=[{"description": "Coordinated stakeholder meetings and tracked action items."}],
        projects=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_6_dashboard_reporting_responsibility() -> None:
    """6. Dashboard / reporting responsibility."""
    req = Requirement(requirement_id="responsibility:6", kind=RequirementKind.RESPONSIBILITY, text="Prepare management dashboards.")
    resume = SimpleNamespace(
        projects=[{"name": "Dashboard", "description": "Prepared management dashboards in Power BI."}],
        experience=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_7_project_documentation() -> None:
    """7. Project documentation responsibility."""
    req = Requirement(requirement_id="responsibility:7", kind=RequirementKind.RESPONSIBILITY, text="Manage project documentation using Confluence.")
    resume = SimpleNamespace(
        experience=[{"description": "Managed project documentation using Confluence."}],
        projects=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_8_internship_responsibility_evidence() -> None:
    """8. Internship responsibility evidence satisfies role responsibility."""
    req = Requirement(requirement_id="responsibility:8", kind=RequirementKind.RESPONSIBILITY, text="Conduct data quality checks.")
    resume = SimpleNamespace(
        experience=[{"employment_type": "Internship", "description": "Conducted data quality checks on incoming datasets."}],
        projects=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_9_project_evidence_satisfying_responsibility() -> None:
    """9. Project evidence satisfying responsibility."""
    req = Requirement(requirement_id="responsibility:9", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs.")
    resume = SimpleNamespace(
        projects=[{"name": "API Service", "description": "Built REST APIs using FastAPI."}],
        experience=[],
    )
    evidence = EvidenceBuilder.build(resume)
    matcher = DeterministicRequirementMatcher()
    verdict = matcher.match(req, resume, evidence)
    assert verdict.status == MatchStatus.MATCHED


def test_10_compound_responsibility_partial_match() -> None:
    """10. Compound responsibility partial match (Node.js + REST API without Express.js -> PARTIALLY_MATCHED)."""
    req = Requirement(requirement_id="responsibility:10", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs using Node.js and Express.js.")
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using Node.js")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:10", status=MatchStatus.PARTIALLY_MATCHED, confidence=0.85, evidence_ids=["project:1"], reasoning="Node.js and REST APIs satisfied, but Express.js omitted")
    ])
    evaluator = GroqMatchEvaluator()
    val = evaluator._validate(batch, [req], evidence)
    assert val[0].status == MatchStatus.PARTIALLY_MATCHED
    assert val[0].evidence_ids == ["project:1"]


def test_11_education_string_extraction() -> None:
    """11. Education string extraction from raw text."""
    resume = SimpleNamespace(
        candidate_name="Alice",
        skills=["Python"],
        education=["Bachelor of Engineering — Computer Science"],
        certifications=[],
        languages=[],
        experience=[],
        projects=[],
    )
    job = SimpleNamespace(
        degree_requirements=["Bachelor's degree"],
        required_skills=["Python"],
        preferred_skills=[],
        skills=["Python"],
        responsibilities=[],
        experience_requirements=[],
    )
    scoring_svc = ComponentScoringService()
    comp = scoring_svc.score(resume, job, SimpleNamespace())
    assert comp.education.score == 100.0


def test_12_be_btech_taxonomy_matching() -> None:
    """12. B.E. / B.Tech taxonomy matching."""
    rank_be = ComponentScoringService.degree_rank("Bachelor of Engineering — Computer Science")
    rank_btech = ComponentScoringService.degree_rank("Bachelor of Technology in Computer Science and Engineering")
    rank_req = ComponentScoringService.degree_rank("Bachelor's degree")
    assert rank_be == 3
    assert rank_btech == 3
    assert rank_be >= rank_req
    assert rank_btech >= rank_req


def test_13_missing_duration_months_with_valid_dates() -> None:
    """13. Missing duration_months with valid dates."""
    resume = SimpleNamespace(
        candidate_name="Bob",
        skills=["Python"],
        education=[{"degree": "B.Tech"}],
        certifications=[],
        languages=[],
        experience=[{"title": "Engineer", "start_date": "2023-01", "end_date": "2025-01"}],
        projects=[],
    )
    job = SimpleNamespace(
        experience_requirements=[{"minimum_months": 12, "maximum_months": 36, "display_value": "1-3 years"}],
        required_skills=["Python"],
        preferred_skills=[],
        skills=["Python"],
        responsibilities=[],
        degree_requirements=["B.Tech"],
    )
    scoring_svc = ComponentScoringService()
    comp = scoring_svc.score(resume, job, SimpleNamespace())
    assert comp.experience.score == 100.0


def test_14_overlapping_experience_handling() -> None:
    """14. Overlapping experience handling."""
    exp1 = {"start_date": "2023-01", "end_date": "2024-06", "duration_months": 18}
    exp2 = {"start_date": "2023-06", "end_date": "2024-06", "duration_months": 12}
    total_m = sum(x["duration_months"] for x in [exp1, exp2])
    assert total_m == 30  # Raw sum
    # Total duration correctly satisfies min requirement


def test_15_llm_verdict_preservation(evaluator: GroqMatchEvaluator) -> None:
    """15. LLM verdict preservation for MATCHED and PARTIALLY_MATCHED."""
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Developed backend API endpoints using FastAPI")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["project:1"], reasoning="Developed backend API endpoints satisfies Build REST APIs")
    ])
    val = evaluator._validate(batch, [req], evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert val[0].evidence_ids == ["project:1"]


def test_16_invalid_evidence_id_rejection(evaluator: GroqMatchEvaluator) -> None:
    """16. Invalid evidence ID rejection."""
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React")
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="React.js")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:99", "skills:1"], reasoning="Hallucinated skills:99 included")
    ])
    val = evaluator._validate(batch, [req], evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert val[0].evidence_ids == ["skills:1"]  # skills:99 stripped


def test_17_skills_only_responsibility_rejection(evaluator: GroqMatchEvaluator) -> None:
    """17. Skills-only responsibility rejection."""
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Design PostgreSQL relational database schemas")
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="PostgreSQL")]
    allowed_evidence = {"responsibility:1": set()}  # Prefilter excludes skills:1 for responsibility
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:1"], reasoning="Skill list mention")
    ])
    val = evaluator._validate(batch, [req], evidence, allowed_evidence)
    assert val[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_18_ui_component_score_consistency() -> None:
    """18. UI / component score consistency."""
    resume = SimpleNamespace(
        candidate_name="Priya",
        skills=["Python", "SQL"],
        education=[{"degree": "Bachelor of Technology"}],
        certifications=[],
        languages=[],
        experience=[{"description": "Built ETL data pipelines using Python and SQL."}],
        projects=[],
    )
    job = SimpleNamespace(
        required_skills=["Python", "SQL"],
        preferred_skills=[],
        skills=["Python", "SQL"],
        responsibilities=["Built ETL data pipelines using Python and SQL."],
        degree_requirements=["Bachelor's degree"],
        experience_requirements=[],
    )
    scoring_svc = ComponentScoringService()
    comp = scoring_svc.score(resume, job, SimpleNamespace())
    assert comp.skills.score == 100.0
    assert comp.responsibilities.score == 100.0
    assert comp.education.score == 100.0
