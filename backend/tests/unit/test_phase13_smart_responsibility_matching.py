import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.schemas.matching import (
    Evidence, LLMVerdictBatch, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, EvidencePrefilter, GroqMatchEvaluator, HybridMatchingService,
)


@pytest.mark.asyncio
async def test_phase13_example_a_deterministic_document_incident_findings():
    """Example A: 'Document incident findings' vs 'Documented findings and escalation recommendations' -> MATCHED, 0 LLM calls."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    evaluator_mock.evaluate = AsyncMock(return_value=[])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Document incident findings"])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(
        projects=[{
            "name": "SOC Lab",
            "description": "Documented incident findings and escalation recommendations after investigating security alerts.",
            "technologies": ["Wazuh"],
        }]
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method in {MatchMethod.EXACT, MatchMethod.ALIAS}
    # Evaluator MUST NOT be called for deterministic match
    assert evaluator_mock.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_phase13_example_b_deterministic_monitor_security_events():
    """Example B: 'Monitor security events' vs 'Monitored security events during the security lab' -> MATCHED, 0 LLM calls."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    evaluator_mock.evaluate = AsyncMock(return_value=[])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Monitor security events"])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(
        projects=[{
            "name": "Security Monitoring Project",
            "description": "Monitored security events during the security lab and correlated logs.",
            "technologies": ["Sysmon"],
        }]
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert evaluator_mock.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_phase13_example_c_deterministic_manage_cloud_infrastructure():
    """Example C: 'Manage cloud infrastructure' vs 'Managed AWS infrastructure deployments' -> MATCHED, 0 LLM calls."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    evaluator_mock.evaluate = AsyncMock(return_value=[])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Manage cloud infrastructure"])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(
        experience=[{
            "title": "Cloud Engineer",
            "company": "Cloud Corp",
            "description": "Managed AWS infrastructure deployments and automated provisioning.",
            "responsibilities": ["Managed AWS infrastructure deployments."],
        }]
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert evaluator_mock.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_phase13_example_d_deterministic_develop_frontend_interfaces():
    """Example D: 'Develop frontend interfaces' vs 'Developed frontend user interfaces using React.js' -> MATCHED, 0 LLM calls."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    evaluator_mock.evaluate = AsyncMock(return_value=[])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Develop frontend interfaces"])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(
        projects=[{
            "name": "Web Dashboard",
            "description": "Developed frontend user interfaces using React.js and Tailwind CSS.",
            "technologies": ["React.js"],
        }]
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert evaluator_mock.evaluate.call_count == 0


@pytest.mark.asyncio
async def test_phase13_fallback_after_deterministic_unresolved():
    """Test LLM IS called after deterministic UNRESOLVED, and recovers semantic match."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    llm_verdict = MatchVerdict(
        requirement_id="responsibility:1",
        status=MatchStatus.MATCHED,
        confidence=0.95,
        evidence_ids=["project:1"],
        reasoning="Wazuh lab configuration proves SIEM alert monitoring execution.",
        method=MatchMethod.LLM_CONFIRMED,
    )
    evaluator_mock.evaluate = AsyncMock(return_value=[llm_verdict])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Monitor security alerts and events from SIEM"])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(
        projects=[{
            "name": "SOC Lab",
            "description": "Configured Wazuh lab to collect and review security events.",
            "technologies": ["Wazuh"],
        }]
    )

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.MATCHED
    assert verdicts[0].method == MatchMethod.LLM_CONFIRMED
    # Evaluator MUST be called exactly once for unresolved item
    assert evaluator_mock.evaluate.call_count == 1


@pytest.mark.asyncio
async def test_phase13_no_false_positive_skill_only_not_satisfying_responsibility():
    """Skill keywords alone without experiential context do not satisfy responsibility."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Monitor security alerts", canonical_value="Monitor security alerts")
    resume = SimpleNamespace(skills=["SIEM", "Splunk", "Wazuh"], projects=[], experience=[], education=[], certifications=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="SIEM, Splunk, Wazuh", canonical_terms=["SIEM", "Splunk", "Wazuh"])]

    v = matcher.match(req, resume, evidence)
    # Must NOT be MATCHED from skill list alone
    assert v.status == MatchStatus.UNRESOLVED


@pytest.mark.asyncio
async def test_phase13_no_match_case_absent_shift_handovers():
    """Requirement with no evidence routes to LLM and returns NO_MATCH."""
    evaluator_mock = MagicMock(spec=GroqMatchEvaluator)
    llm_verdict = MatchVerdict(
        requirement_id="responsibility:1",
        status=MatchStatus.NO_MATCH,
        confidence=1.0,
        evidence_ids=[],
        reasoning="No 24/7 shift handover evidence found.",
        method=MatchMethod.LLM_REJECTED,
    )
    evaluator_mock.evaluate = AsyncMock(return_value=[llm_verdict])
    hybrid = HybridMatchingService(evaluator=evaluator_mock)

    job = SimpleNamespace(responsibilities=["Participate in 24/7 production shift handovers"])
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    extracted = SimpleNamespace(projects=[], experience=[])

    enriched, verdicts = await hybrid.match(job, resume, extracted, config=None)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.NO_MATCH
    assert evaluator_mock.evaluate.call_count == 0
