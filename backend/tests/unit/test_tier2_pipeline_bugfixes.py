import pytest
from unittest.mock import AsyncMock, patch

from app.schemas.matching import (
    Evidence,
    MatchMethod,
    MatchStatus,
    Requirement,
    RequirementKind,
)
from app.services.matching_service import (
    GroqMatchEvaluator,
    HybridMatchingService,
    _parse_llm_batch_response,
)


def test_bug2_score_reasoning_contradiction_is_corrected():
    """
    Bug 2: When LLM outputs reasoning like 'None of the provided evidence mentions cloud architecture experience'
    or sets sub-claims to none, but coverage_score was defaulted or set high, validator must force coverage_score=0.0
    and status=NO_MATCH.
    """
    evaluator = GroqMatchEvaluator()
    requirements = [
        Requirement(
            requirement_id="responsibility:1",
            kind=RequirementKind.RESPONSIBILITY,
            text="Experience working with cloud architectures",
            required=True,
        )
    ]
    evidence = [
        Evidence(
            evidence_id="experience:1",
            kind="experience",
            text="Worked on frontend React components and state management.",
            canonical_terms=["react", "state"],
        )
    ]

    raw_llm_json = """
    {
      "verdicts": [
        {
          "requirement_id": "responsibility:1",
          "sub_claims": ["cloud architectures"],
          "sub_claim_evidence": [
            {
              "claim": "cloud architectures",
              "evidence_level": "none",
              "note": "No cloud experience in candidate profile"
            }
          ],
          "coverage_score": 1.0,
          "importance": "critical",
          "reasoning": "None of the provided evidence mentions cloud architecture experience."
        }
      ]
    }
    """
    parsed = _parse_llm_batch_response(raw_llm_json, requirements)
    verdicts = evaluator._validate(parsed, requirements, evidence)

    assert len(verdicts) == 1
    verdict = verdicts[0]
    # Assert contradiction was caught and corrected to 0% Match / NO_MATCH
    assert verdict.coverage_score == 0.0
    assert verdict.status == MatchStatus.NO_MATCH
    assert verdict.method == MatchMethod.LLM_REJECTED
    assert "None of the provided evidence mentions" in verdict.reasoning


def test_parse_llm_batch_response_resilience_and_id_mapping():
    """
    Verify _parse_llm_batch_response handles:
    1. Markdown code block wrapping
    2. Bare JSON lists
    3. Delimiter variations (e.g. 'responsibility-1', 'responsibility 1' -> 'responsibility:1')
    4. Text-based requirement matching
    5. Numeric 1-based index mapping
    """
    requirements = [
        Requirement(
            requirement_id="skill:1",
            kind=RequirementKind.SKILL,
            text="Python",
            required=True,
        ),
        Requirement(
            requirement_id="responsibility:1",
            kind=RequirementKind.RESPONSIBILITY,
            text="Design scalable REST APIs",
            required=True,
        ),
    ]

    # Markdown wrapped + bare array with delimiter variation and text matching
    markdown_json = """```json
    [
      {
        "requirement_id": "skill-1",
        "coverage_score": 0.9,
        "reasoning": "Direct Python experience found."
      },
      {
        "requirement_id": "Design scalable REST APIs",
        "coverage_score": 0.8,
        "reasoning": "Candidate designed multiple FastAPI and Flask microservices."
      }
    ]
    ```"""

    parsed = _parse_llm_batch_response(markdown_json, requirements)
    assert len(parsed.verdicts) == 2
    assert parsed.verdicts[0].requirement_id == "skill:1"
    assert parsed.verdicts[0].coverage_score == 0.9
    assert parsed.verdicts[1].requirement_id == "responsibility:1"
    assert parsed.verdicts[1].coverage_score == 0.8


@pytest.mark.asyncio
async def test_bug1_evaluation_failed_surfaces_instead_of_silent_stub():
    """
    Bug 1: When LLM evaluator fails / is unavailable for unresolved requirements,
    the system must emit MatchStatus.EVALUATION_FAILED instead of silently falling back
    to un-evaluated deterministic stubs.
    """
    service = HybridMatchingService()

    class MockJob:
        skills = []
        responsibilities = ["Design scalable cloud microservices"]
        preferred_skills = []
        degree_requirements = []
        experience_requirements = []
        certifications = []
        project_requirements = []

    class MockResume:
        id = "candidate-123"
        skills = ["Python"]
        experience = [{"title": "Engineer", "description": "Worked on backend microservices and cloud"}]
        projects = []
        degree_requirements = []

    class MockExtracted:
        projects = [{"name": "Cloud App", "description": "Built backend microservices on cloud"}]

    # Mock the evaluator to fail / return empty verdicts (simulating timeout or provider failure)
    with patch.object(service.evaluator, "evaluate", new=AsyncMock(return_value=([], {}))):
        _, verdicts = await service.match(MockJob(), MockResume(), MockExtracted())

    assert len(verdicts) >= 1
    resp_verdict = next((v for v in verdicts if "cloud microservices" in (v.requirement_text or "")), None)
    assert resp_verdict is not None
    # Must NOT be masked as simple UNMET or have the canned deterministic stub
    assert resp_verdict.status == MatchStatus.EVALUATION_FAILED
    assert resp_verdict.method == MatchMethod.EVALUATION_FAILED
    assert "AI evaluation could not be completed" in resp_verdict.reasoning
