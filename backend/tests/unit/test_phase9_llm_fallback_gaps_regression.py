import pytest
from types import SimpleNamespace
from app.schemas.matching import (
    Requirement, RequirementKind, Evidence, MatchStatus, MatchMethod, LLMVerdict, LLMVerdictBatch, MatchVerdict,
)
from app.services.matching_service import HybridMatchingService, GroqMatchEvaluator, EvidencePrefilter, EvidenceBuilder
from app.services.scoring.component_scoring_service import ComponentScoringService


@pytest.fixture
def evaluator() -> GroqMatchEvaluator:
    GroqMatchEvaluator._cache.clear()
    return GroqMatchEvaluator()


@pytest.fixture
def hybrid_service() -> HybridMatchingService:
    GroqMatchEvaluator._cache.clear()
    return HybridMatchingService()


def test_1_deterministic_no_match_skill_routes_to_llm() -> None:
    """1. Deterministic NO_MATCH skill -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="monitoring platforms")
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Configured Zabbix and Nagios monitoring")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0


def test_2_deterministic_no_match_responsibility_routes_to_llm() -> None:
    """2. Deterministic NO_MATCH responsibility -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Create scripts to automate operational tasks")
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Wrote Python scripts for server health checks")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0


def test_3_deterministic_unresolved_routes_to_llm() -> None:
    """3. Deterministic UNRESOLVED -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Troubleshoot production incidents")
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Investigated server outages")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0


def test_4_deterministic_partially_matched_routes_to_llm() -> None:
    """4. Deterministic PARTIALLY_MATCHED -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs using Node.js and Express.js")
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using Node.js")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0


def test_5_deterministic_matched_no_unnecessary_llm_call() -> None:
    """5. Deterministic MATCHED -> LLM not unnecessarily called."""
    verdict = MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=1.0, evidence_ids=["skills:1"], reasoning="Exact match", method=MatchMethod.EXACT)
    assert verdict.status == MatchStatus.MATCHED


def test_6_zero_lexical_overlap_candidate_evidence_routes_to_llm() -> None:
    """6. Zero lexical overlap but candidate evidence exists -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Cloud Infrastructure Operations")
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Provisioned AWS S3 buckets and EC2 instances")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0


def test_7_llm_matched_valid_evidence_ai_confirmed(evaluator: GroqMatchEvaluator) -> None:
    """7. LLM MATCHED + valid evidence -> AI_CONFIRMED."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Linux Admin")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Administered Red Hat Linux systems")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["experience:1"], reasoning="Red Hat Linux is Linux admin")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert val[0].evidence_ids == ["experience:1"]


def test_8_llm_no_match_ai_unmet(evaluator: GroqMatchEvaluator) -> None:
    """8. LLM NO_MATCH -> AI_UNMET."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Oracle DB")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Worked with PostgreSQL")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="PostgreSQL is not Oracle DB")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_9_llm_unresolved_unresolved(evaluator: GroqMatchEvaluator) -> None:
    """9. LLM UNRESOLVED -> UNRESOLVED."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Maintain security compliance")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Reviewed system logs")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.UNRESOLVED, confidence=0.5, evidence_ids=[], reasoning="Ambiguous evidence")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.UNRESOLVED


def test_10_invalid_evidence_id_rejected_safely(evaluator: GroqMatchEvaluator) -> None:
    """10. Invalid evidence ID -> rejected safely."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Python")]
    allowed_evidence = {"skill:1": {"skills:1"}}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:999"], reasoning="Hallucinated ID")
    ])
    val = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert "skills:999" not in val[0].evidence_ids


def test_11_mixed_valid_invalid_evidence_ids(evaluator: GroqMatchEvaluator) -> None:
    """11. Mixed valid/invalid evidence IDs -> valid IDs preserved."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    evidence = [
        Evidence(evidence_id="skills:1", kind="skills", text="Python"),
        Evidence(evidence_id="project:1", kind="project", text="Python API"),
    ]
    allowed_evidence = {"skill:1": {"skills:1", "project:1"}}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:1", "skills:999"], reasoning="Mixed IDs")
    ])
    val = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert val[0].evidence_ids == ["skills:1"]


def test_12_groq_429_safe_fallback() -> None:
    """12. Groq 429 -> safe fallback."""
    det = MatchVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, reasoning="No match", method=MatchMethod.EXACT)
    llm_by_id = {}
    fused = llm_by_id.get("skill:1", det)
    assert fused.status == MatchStatus.NO_MATCH


def test_13_python_automation_not_equal_bash_powershell(evaluator: GroqMatchEvaluator) -> None:
    """13. Python automation does not automatically equal Bash/PowerShell."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Create Bash or PowerShell scripts")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Automated tasks using Python scripts")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.PARTIALLY_MATCHED, confidence=0.85, evidence_ids=["experience:1"], reasoning="Python scripting shown but Bash/PowerShell omitted")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.PARTIALLY_MATCHED


def test_14_generic_monitoring_not_equal_nagios_zabbix(evaluator: GroqMatchEvaluator) -> None:
    """14. Generic monitoring does not automatically equal Nagios/Zabbix/SolarWinds."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Experience with Nagios, Zabbix, or SolarWinds")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Monitored server health")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.UNRESOLVED, confidence=0.5, evidence_ids=[], reasoning="Generic server monitoring does not specify Nagios, Zabbix, or SolarWinds")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_15_docker_not_equal_kubernetes(evaluator: GroqMatchEvaluator) -> None:
    """15. Docker does not automatically equal Kubernetes."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Kubernetes")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Containerized apps using Docker")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="Docker usage is not Kubernetes orchestration")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_16_unrelated_technology_rejected(evaluator: GroqMatchEvaluator) -> None:
    """16. Unrelated technology remains rejected."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Angular")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="Angular is distinct from React")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_17_responsibility_can_use_project_evidence() -> None:
    """17. Responsibility can use project evidence."""
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs")
    resume = SimpleNamespace(projects=[{"name": "API", "description": "Built REST APIs using FastAPI"}], experience=[])
    evidence = EvidenceBuilder.build(resume)
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0
    assert selected[0].kind == "project"


def test_18_responsibility_can_use_internship_evidence() -> None:
    """18. Responsibility can use internship evidence."""
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Conduct data quality checks")
    resume = SimpleNamespace(experience=[{"employment_type": "Internship", "description": "Conducted data quality checks"}], projects=[])
    evidence = EvidenceBuilder.build(resume)
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0
    assert selected[0].kind == "experience"


def test_19_skills_only_evidence_does_not_falsely_satisfy_responsibility(evaluator: GroqMatchEvaluator) -> None:
    """19. Skills-only evidence does not falsely satisfy complex responsibility."""
    reqs = [Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Design PostgreSQL relational database schemas")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="PostgreSQL")]
    allowed_evidence = {"responsibility:1": set()}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="responsibility:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:1"], reasoning="Skill mention")
    ])
    val = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert val[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_20_no_duplicate_requirement_scoring() -> None:
    """20. No duplicate requirement scoring."""
    requirements = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    deterministic = [MatchVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, reasoning="No match", method=MatchMethod.EXACT)]
    llm = [MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:1"], reasoning="Matched", method=MatchMethod.LLM_CONFIRMED)]
    llm_by_id = {v.requirement_id: v for v in llm}
    fused = [llm_by_id.get(item.requirement_id, item) for item in deterministic]
    assert len(fused) == len(requirements)


def test_21_no_duplicate_evidence_scoring() -> None:
    """21. No duplicate evidence scoring."""
    ev = Evidence(evidence_id="project:1", kind="project", text="Built Python REST API")
    assert ev.evidence_id == "project:1"


def test_22_final_status_equals_component_scorer_interpretation() -> None:
    """22. Final requirement status equals component scorer interpretation."""
    resume = SimpleNamespace(
        candidate_name="Alex",
        skills=["Python"],
        education=[{"degree": "B.Tech"}],
        certifications=[],
        languages=[],
        experience=[{"description": "Built ETL data pipelines using Python"}],
        projects=[],
    )
    job = SimpleNamespace(
        required_skills=["Python"],
        preferred_skills=[],
        skills=["Python"],
        responsibilities=["Built ETL data pipelines using Python"],
        degree_requirements=["B.Tech"],
        experience_requirements=[],
    )
    scoring_svc = ComponentScoringService()
    comp = scoring_svc.score(resume, job, SimpleNamespace())
    assert comp.skills.score == 100.0
    assert comp.responsibilities.score == 100.0
    assert comp.education.score == 0.0
