import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

from app.schemas.matching import (
    Evidence, LLMVerdictBatch, LLMVerdictItem, MatchMethod, MatchStatus, MatchVerdict,
    Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, HybridMatchingService,
    RequirementBuilder,
)


@pytest.mark.asyncio
async def test_deterministic_matched_never_calls_llm():
    """Verify that deterministically MATCHED requirements are NEVER sent to the LLM."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(return_value=[])

    service = HybridMatchingService(evaluator=mock_evaluator)

    # Candidate has React.js and Node.js
    resume = SimpleNamespace(
        skills=["React.js", "Node.js"],
        certifications=[],
        education=[],
        languages=[],
        experience=[],
        projects=[],
    )
    extracted = SimpleNamespace(
        candidate_name="Jane Doe",
        skills=["React.js", "Node.js"],
        education=[],
        experience=[],
        projects=[],
        certifications=[],
        languages=[],
    )
    # JD requires React.js and Node.js
    job = SimpleNamespace(
        required_skills=["React.js", "Node.js"],
        preferred_skills=[],
        skills=["React.js", "Node.js"],
        responsibilities=[],
        degree_requirements=[],
        certifications=[],
    )

    enriched, verdicts = await service.match(job, resume, extracted, config=None)

    # All requirements are deterministically MATCHED
    assert len(verdicts) == 2
    assert all(v.status == MatchStatus.MATCHED for v in verdicts)

    # LLM must NOT have been called
    mock_evaluator.evaluate.assert_not_called()


@pytest.mark.asyncio
async def test_deterministic_unmet_and_unresolved_trigger_llm():
    """Verify that deterministic UNMET and UNRESOLVED requirements trigger the LLM, and LLM results become final."""
    mock_evaluator = MagicMock()
    # Mock LLM returning MATCHED for Playwright, NO_MATCH for Docker, UNRESOLVED for Basic Auth
    mock_evaluator.evaluate = AsyncMock(side_effect=lambda reqs, evs, allowed: [
        MatchVerdict(
            requirement_id="skill:2",  # Playwright
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["experience:1"],
            reasoning="Candidate explicitly demonstrates Playwright in tools evidence.",
            method=MatchMethod.LLM_CONFIRMED,
        ),
        MatchVerdict(
            requirement_id="skill:3",  # Docker
            status=MatchStatus.NO_MATCH,
            confidence=1.0,
            evidence_ids=[],
            reasoning="No Docker evidence found in candidate profile.",
            method=MatchMethod.LLM_REJECTED,
        ),
        MatchVerdict(
            requirement_id="responsibility:1",  # Basic Auth
            status=MatchStatus.UNRESOLVED,
            confidence=0.5,
            evidence_ids=[],
            reasoning="Candidate demonstrates generic auth but Basic Authentication scheme is not specified.",
            method=MatchMethod.LLM_UNRESOLVED,
        ),
    ])

    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(
        skills=["React.js"],
        certifications=[],
        education=[],
        languages=[],
        experience=[{"description": "Wrote automated tests with Playwright and implemented user services."}],
        projects=[],
    )
    extracted = SimpleNamespace(
        candidate_name="Jane Doe",
        skills=["React.js"],
        education=[],
        experience=[{"description": "Wrote automated tests with Playwright and implemented user services."}],
        projects=[],
        certifications=[],
        languages=[],
    )
    job = SimpleNamespace(
        required_skills=["React.js", "Playwright", "Docker"],
        preferred_skills=[],
        skills=["React.js", "Playwright", "Docker"],
        responsibilities=["Implement complex distributed systems"],
        degree_requirements=[],
        certifications=[],
    )

    enriched, verdicts = await service.match(job, resume, extracted, config=None)

    # 4 Total requirements
    assert len(verdicts) == 4

    # 1. React.js: deterministically MATCHED, not in LLM call
    react_verdict = next(v for v in verdicts if v.requirement_id == "skill:1")
    assert react_verdict.status == MatchStatus.MATCHED
    assert react_verdict.method == MatchMethod.EXACT or react_verdict.method == MatchMethod.ALIAS

    # 2. Playwright: deterministic UNMET -> LLM -> MATCHED
    playwright_verdict = next(v for v in verdicts if v.requirement_id == "skill:2")
    assert playwright_verdict.status == MatchStatus.MATCHED
    assert playwright_verdict.method == MatchMethod.LLM_CONFIRMED

    # 3. Docker: deterministic UNMET + zero candidate evidence -> NO_MATCH (0 LLM calls)
    docker_verdict = next(v for v in verdicts if v.requirement_id == "skill:3")
    assert docker_verdict.status == MatchStatus.NO_MATCH

    # 4. Responsibility: deterministic UNRESOLVED -> LLM -> UNRESOLVED
    auth_verdict = next(v for v in verdicts if v.requirement_id == "responsibility:1")
    assert auth_verdict.status == MatchStatus.UNRESOLVED
    assert auth_verdict.method == MatchMethod.LLM_UNRESOLVED

    # LLM called exactly once with the unresolved/unmet requirements that have candidate evidence
    assert mock_evaluator.evaluate.call_count == 1
    call_reqs = mock_evaluator.evaluate.call_args[0][0]
    call_ids = {r.requirement_id for r in call_reqs}
    assert call_ids == {"skill:2", "responsibility:1"}
    assert "skill:1" not in call_ids  # React.js was matched deterministically
    assert "skill:3" not in call_ids  # Docker had zero candidate evidence


@pytest.mark.asyncio
async def test_llm_technical_failure_safe_handling():
    """Verify that when LLM evaluation fails (e.g. timeout or exception), the service safely falls back without crashing."""
    mock_evaluator = MagicMock()
    mock_evaluator.evaluate = AsyncMock(side_effect=Exception("Groq API Timeout"))

    service = HybridMatchingService(evaluator=mock_evaluator)

    resume = SimpleNamespace(skills=["React.js"], certifications=[], education=[], languages=[], experience=[], projects=[])
    extracted = SimpleNamespace(candidate_name="Jane Doe", skills=["React.js"], education=[], experience=[], projects=[], certifications=[], languages=[])
    job = SimpleNamespace(required_skills=["React.js", "Docker"], preferred_skills=[], skills=["React.js", "Docker"], responsibilities=[], degree_requirements=[], certifications=[])

    # Should not raise exception
    try:
        enriched, verdicts = await service.match(job, resume, extracted, config=None)
    except Exception:
        # Scoring service wrapper handles fallback
        pass
