import pytest
from unittest.mock import AsyncMock, MagicMock
from types import SimpleNamespace

from app.schemas.matching import (
    Evidence, LLMVerdictBatch, LLMVerdictItem, MatchMethod, MatchStatus, MatchVerdict,
    Requirement, RequirementKind,
)
from app.services.matching_service import (
    EvidenceBuilder, GroqMatchEvaluator, HybridMatchingService, RequirementBuilder,
)


def test_invalid_evidence_id_rejected():
    """Verify that if an LLM returns MATCHED with an invalid or hallucinated evidence ID, it is rejected and downgraded to UNRESOLVED."""
    evaluator = GroqMatchEvaluator()
    requirements = [
        Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Docker", required=True)
    ]
    evidence = [
        Evidence(evidence_id="skills:1", kind="skills", text="React.js, Node.js, MongoDB", canonical_terms=["React.js", "Node.js", "MongoDB"])
    ]

    # LLM hallucinates MATCHED citing non-existent FAKE_ID
    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(
            requirement_id="skill:1",
            status=MatchStatus.MATCHED,
            confidence=0.99,
            evidence_ids=["FAKE_ID"],
            reasoning="Candidate probably knows Docker.",
        )
    ])

    verdicts = evaluator._validate(batch, requirements, evidence)
    assert len(verdicts) == 1
    # Must NOT be MATCHED
    assert verdicts[0].status == MatchStatus.UNRESOLVED
    assert verdicts[0].method == MatchMethod.LLM_UNRESOLVED
    assert "Rejected" in verdicts[0].reasoning


def test_empty_evidence_id_on_matched_rejected():
    """Verify that MATCHED with empty evidence_ids is rejected."""
    evaluator = GroqMatchEvaluator()
    requirements = [
        Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="AWS", required=True)
    ]
    evidence = [
        Evidence(evidence_id="skills:1", kind="skills", text="React.js, Node.js", canonical_terms=["React.js", "Node.js"])
    ]

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(
            requirement_id="skill:1",
            status=MatchStatus.MATCHED,
            confidence=0.90,
            evidence_ids=[],
            reasoning="Candidate has cloud affinity.",
        )
    ])

    verdicts = evaluator._validate(batch, requirements, evidence)
    assert len(verdicts) == 1
    assert verdicts[0].status == MatchStatus.UNRESOLVED
    assert verdicts[0].method == MatchMethod.LLM_UNRESOLVED


def test_evidence_grounded_validation_scenarios():
    """Verify standard grounded evaluations: MATCHED with valid citation, NO_MATCH, and UNRESOLVED."""
    evaluator = GroqMatchEvaluator()
    requirements = [
        Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="Playwright", required=True),
        Requirement(requirement_id="skill:2", kind=RequirementKind.SKILL, text="Docker", required=True),
        Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Basic Authentication", required=True),
        Requirement(requirement_id="responsibility:2", kind=RequirementKind.RESPONSIBILITY, text="CRUD Operations", required=True),
    ]
    evidence = [
        Evidence(evidence_id="skills:1", kind="skills", text="React.js, Node.js, Playwright", canonical_terms=["React.js", "Node.js", "Playwright"]),
        Evidence(evidence_id="experience:1", kind="experience", text="Implemented secure login authentication", canonical_terms=[]),
        Evidence(evidence_id="project:1", kind="project", text="Built APIs for creating, reading, updating and deleting database records", canonical_terms=[]),
    ]

    batch = LLMVerdictBatch(verdicts=[
        LLMVerdictItem(
            requirement_id="skill:1",
            status=MatchStatus.MATCHED,
            confidence=0.95,
            evidence_ids=["skills:1"],
            reasoning="Playwright explicitly present in candidate skills evidence.",
        ),
        LLMVerdictItem(
            requirement_id="skill:2",
            status=MatchStatus.NO_MATCH,
            confidence=1.0,
            evidence_ids=[],
            reasoning="No Docker evidence found in candidate profile.",
        ),
        LLMVerdictItem(
            requirement_id="responsibility:1",
            status=MatchStatus.UNRESOLVED,
            confidence=0.4,
            evidence_ids=["experience:1"],
            reasoning="Generic authentication is demonstrated but Basic Auth scheme is unspecified.",
        ),
        LLMVerdictItem(
            requirement_id="responsibility:2",
            status=MatchStatus.MATCHED,
            confidence=0.90,
            evidence_ids=["project:1"],
            reasoning="Project explicitly details creating, reading, updating and deleting records.",
        ),
    ])

    verdicts = evaluator._validate(batch, requirements, evidence)
    assert len(verdicts) == 4

    v_playwright = next(v for v in verdicts if v.requirement_id == "skill:1")
    assert v_playwright.status == MatchStatus.MATCHED
    assert v_playwright.method == MatchMethod.LLM_CONFIRMED
    assert v_playwright.evidence_ids == ["skills:1"]

    v_docker = next(v for v in verdicts if v.requirement_id == "skill:2")
    assert v_docker.status == MatchStatus.NO_MATCH
    assert v_docker.method == MatchMethod.LLM_REJECTED

    v_basic_auth = next(v for v in verdicts if v.requirement_id == "responsibility:1")
    assert v_basic_auth.status == MatchStatus.UNRESOLVED
    assert v_basic_auth.method == MatchMethod.LLM_UNRESOLVED

    v_crud = next(v for v in verdicts if v.requirement_id == "responsibility:2")
    assert v_crud.status == MatchStatus.MATCHED
    assert v_crud.method == MatchMethod.LLM_CONFIRMED
    assert v_crud.evidence_ids == ["project:1"]
