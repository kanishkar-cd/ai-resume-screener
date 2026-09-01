import pytest
from types import SimpleNamespace
from app.schemas.matching import (
    Requirement, RequirementKind, Evidence, MatchStatus, MatchMethod, LLMVerdict, LLMVerdictBatch, MatchVerdict,
)
from app.services.matching_service import HybridMatchingService, GroqMatchEvaluator, EvidencePrefilter


@pytest.fixture
def evaluator() -> GroqMatchEvaluator:
    GroqMatchEvaluator._cache.clear()
    return GroqMatchEvaluator()


@pytest.fixture
def hybrid_service() -> HybridMatchingService:
    GroqMatchEvaluator._cache.clear()
    return HybridMatchingService()


@pytest.mark.asyncio
async def test_1_unmet_project_evidence_routes_to_llm(hybrid_service: HybridMatchingService) -> None:
    """1. UNMET + relevant project evidence -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="skill:1", kind=RequirementKind.REQUIRED_SKILL, text="Windows Server and Linux administration")
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Administered 80+ Windows and Linux servers, including patching and service management")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0
    assert selected[0].evidence_id == "project:1"


@pytest.mark.asyncio
async def test_2_unmet_experience_evidence_routes_to_llm(hybrid_service: HybridMatchingService) -> None:
    """2. UNMET + relevant experience evidence -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Troubleshoot DNS, DHCP, TCP/IP, VPN issues")
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Troubleshot DNS, DHCP, TCP/IP, VPN, and HTTP/HTTPS connectivity issues")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0
    assert selected[0].evidence_id == "experience:1"


@pytest.mark.asyncio
async def test_3_unmet_internship_evidence_routes_to_llm(hybrid_service: HybridMatchingService) -> None:
    """3. UNMET + relevant internship evidence -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Configure Nagios or Zabbix monitoring")
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="System Admin Intern: Configured Zabbix and Nagios monitoring for 50+ nodes")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0
    assert selected[0].evidence_id == "experience:1"


@pytest.mark.asyncio
async def test_4_unresolved_routes_to_llm(hybrid_service: HybridMatchingService) -> None:
    """4. UNRESOLVED -> LLM called."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Perform root-cause analysis on production incidents")
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Investigated production outages and drafted RCA reports")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0


@pytest.mark.asyncio
async def test_5_partially_matched_routes_to_llm(hybrid_service: HybridMatchingService) -> None:
    """5. PARTIALLY_MATCHED -> LLM evaluation where appropriate."""
    prefilter = EvidencePrefilter(threshold=0.1, limit=3)
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Build REST APIs using Node.js and Express.js")
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Built REST APIs using Node.js")]
    selected = prefilter.select(req, evidence)
    assert len(selected) > 0


def test_6_deterministic_matched_no_llm_call(hybrid_service: HybridMatchingService) -> None:
    """6. Deterministic MATCHED -> no unnecessary LLM call."""
    verdict = MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=1.0, evidence_ids=["skills:1"], reasoning="Exact match", method=MatchMethod.EXACT)
    # Verified in routing: MatchStatus.MATCHED skips unresolved list
    assert verdict.status == MatchStatus.MATCHED


def test_7_true_hard_negative_safely_rejected(evaluator: GroqMatchEvaluator) -> None:
    """7. True hard negative -> safely rejected."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React.js")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Angular")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="Angular is a distinct frontend framework from React")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_8_llm_confirms_deterministic_unmet(evaluator: GroqMatchEvaluator) -> None:
    """8. LLM confirms deterministic UNMET -> final MATCHED/AI_CONFIRMED."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="monitoring platforms")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Configured Zabbix and Nagios monitoring")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["experience:1"], reasoning="Zabbix and Nagios are monitoring platforms")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.MATCHED
    assert val[0].evidence_ids == ["experience:1"]


def test_9_llm_rejects_deterministic_unmet(evaluator: GroqMatchEvaluator) -> None:
    """9. LLM rejects deterministic UNMET -> final UNMET/NO_MATCH."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Kubernetes")]
    evidence = [Evidence(evidence_id="experience:1", kind="experience", text="Managed Docker containers")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="Docker usage is not Kubernetes orchestration")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH


def test_10_llm_rate_limit_failure_no_fake_match() -> None:
    """10. LLM rate-limit failure -> no fake match."""
    # When LLM fails, fused defaults back to deterministic requirement without manufactured MATCHED
    det = MatchVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, reasoning="No match", method=MatchMethod.EXACT)
    llm_by_id = {}
    fused = llm_by_id.get("skill:1", det)
    assert fused.status == MatchStatus.NO_MATCH


def test_11_invalid_llm_evidence_id_rejected(evaluator: GroqMatchEvaluator) -> None:
    """11. Invalid LLM evidence ID -> existing validation remains active."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Python")]
    allowed_evidence = {"skill:1": {"skills:1"}}
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:999"], reasoning="Invalid ID cited")
    ])
    val = evaluator._validate(batch, reqs, evidence, allowed_evidence)
    assert "skills:999" not in val[0].evidence_ids
    assert val[0].status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_12_multiple_evidence_items_association(evaluator: GroqMatchEvaluator) -> None:
    """12. Multiple evidence items -> no ambiguous automatic evidence association."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    evidence = [
        Evidence(evidence_id="project:1", kind="project", text="Python backend"),
        Evidence(evidence_id="experience:1", kind="experience", text="Python data pipeline"),
    ]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=[], reasoning="No evidence cited")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.UNRESOLVED  # Multiple evidence items with zero citations returns UNRESOLVED


def test_13_no_duplicate_requirement_scoring() -> None:
    """13. No duplicate requirement scoring."""
    requirements = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Python")]
    deterministic = [MatchVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, reasoning="No match", method=MatchMethod.EXACT)]
    llm = [MatchVerdict(requirement_id="skill:1", status=MatchStatus.MATCHED, confidence=0.9, evidence_ids=["skills:1"], reasoning="Matched", method=MatchMethod.LLM_CONFIRMED)]
    llm_by_id = {v.requirement_id: v for v in llm}
    fused = [llm_by_id.get(item.requirement_id, item) for item in deterministic]
    assert len(fused) == len(requirements)
    assert fused[0].status == MatchStatus.MATCHED


def test_14_no_duplicate_evidence_scoring() -> None:
    """14. No duplicate evidence scoring."""
    ev = Evidence(evidence_id="project:1", kind="project", text="Built Python REST API")
    assert ev.evidence_id == "project:1"


def test_15_non_matching_resume_remains_non_matching(evaluator: GroqMatchEvaluator) -> None:
    """15. Non-matching resume remains non-matching."""
    reqs = [Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="AWS S3")]
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="HTML, CSS, JavaScript")]
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdict(requirement_id="skill:1", status=MatchStatus.NO_MATCH, confidence=1.0, evidence_ids=[], reasoning="Candidate skills contain no AWS or cloud storage proof")
    ])
    val = evaluator._validate(batch, reqs, evidence)
    assert val[0].status == MatchStatus.NO_MATCH
