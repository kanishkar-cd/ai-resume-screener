import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, EvidencePrefilter, GroqMatchEvaluator, HybridMatchingService,
)
from app.services.scoring.component_scoring_service import ComponentScoringService


def _run_matcher(req_kind: RequirementKind, req_text: str, candidate_skills: list[str] = None, projects: list[dict] = None, experience: list[dict] = None) -> MatchVerdict:
    matcher = DeterministicRequirementMatcher()
    resume = SimpleNamespace(
        skills=candidate_skills or [],
        certifications=[],
        education=[],
        experience=experience or [],
        projects=projects or [],
    )
    extracted = SimpleNamespace(
        candidate_name="Test Candidate",
        skills=candidate_skills or [],
        education=[],
        certifications=[],
        languages=[],
        experience=experience or [],
        projects=projects or [],
    )
    evidence = EvidenceBuilder.build(extracted)
    req = Requirement(requirement_id="responsibility:1", kind=req_kind, text=req_text, canonical_value=req_text)
    return matcher.match(req, resume, evidence)


def test_phase9_software_engineering_project_responsibility():
    """Software Engineering: Project implementation satisfies backend API responsibility."""
    projects = [{
        "name": "Backend API Service",
        "technologies": ["Node.js", "Express.js"],
        "description": "Built and maintained backend APIs using Node.js and Express.js.",
    }]
    v = _run_matcher(RequirementKind.RESPONSIBILITY, "Build and maintain backend APIs", projects=projects)
    assert v.status == MatchStatus.MATCHED
    assert any("project" in str(eid) for eid in v.evidence_ids)


def test_phase9_qa_automated_testing_responsibility():
    """QA: Project test suite satisfies automated testing responsibility."""
    projects = [{
        "name": "E2E Testing Suite",
        "technologies": ["Playwright"],
        "description": "Created Playwright end to end tests and debugged defects.",
    }]
    v = _run_matcher(RequirementKind.RESPONSIBILITY, "Execute automated testing and debug defects", projects=projects)
    assert v.status == MatchStatus.MATCHED


def test_phase9_data_engineering_pipeline_responsibility():
    """Data Engineering: Project ETL satisfies data pipeline responsibility."""
    projects = [{
        "name": "Data Ingestion Pipeline",
        "technologies": ["Python", "SQL"],
        "description": "Developed and maintained data pipelines using Python and SQL.",
    }]
    v = _run_matcher(RequirementKind.RESPONSIBILITY, "Build and maintain data pipelines", projects=projects)
    assert v.status == MatchStatus.MATCHED


def test_phase9_negative_skill_keyword_not_satisfying_responsibility():
    """Negative test: MongoDB in skills alone does NOT satisfy CRUD operations responsibility."""
    v = _run_matcher(RequirementKind.RESPONSIBILITY, "Implement CRUD operations", candidate_skills=["MongoDB"])
    # Skills alone must NOT return MATCHED
    assert v.status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_phase9_negative_github_not_satisfying_github_actions_pipeline():
    """Negative test: GitHub tool mention alone does NOT satisfy GitHub Actions CI/CD."""
    v = _run_matcher(RequirementKind.RESPONSIBILITY, "Use GitHub Actions for CI/CD", candidate_skills=["GitHub"])
    assert v.status in {MatchStatus.UNRESOLVED, MatchStatus.NO_MATCH}


def test_phase9_experience_production_incident_investigation():
    """Experience: Professional experience satisfies incident investigation responsibility."""
    experience = [{
        "title": "SRE Engineer",
        "company": "Tech Corp",
        "description": "Investigated production incidents and documented root causes.",
        "responsibilities": ["Investigated production incidents and documented root causes."],
    }]
    v = _run_matcher(RequirementKind.RESPONSIBILITY, "Investigate production incidents and document root causes", experience=experience)
    assert v.status == MatchStatus.MATCHED
    assert any("experience" in str(eid) for eid in v.evidence_ids)


def test_phase9_fresher_academic_security_log_analysis():
    """Fresher: Academic lab log correlation satisfies security log analysis."""
    projects = [{
        "name": "SOC Lab",
        "technologies": ["Wazuh", "Linux", "Windows"],
        "description": "Reviewed security logs and correlated suspicious events across Linux and Windows endpoints.",
    }]
    v = _run_matcher(RequirementKind.RESPONSIBILITY, "Analyze security logs and correlate events", projects=projects)
    assert v.status == MatchStatus.MATCHED


def test_phase9_llm_evaluator_payload_multi_domain_guidelines():
    """Verify GroqMatchEvaluator payload includes generic multi-domain guidelines."""
    evaluator = GroqMatchEvaluator()
    req = Requirement(requirement_id="responsibility:1", kind=RequirementKind.RESPONSIBILITY, text="Monitor SIEM security alerts")
    evidence = [Evidence(evidence_id="project:1", kind="project", text="Configured Wazuh lab to collect and review security events", canonical_terms=["Wazuh"])]

    payload = evaluator._payload([req], evidence)
    system_content = payload["messages"][0]["content"]

    # Verify generic multi-domain prompt inclusions
    assert "Software Engineering" in system_content
    assert "QA / Testing" in system_content
    assert "SecOps / SOC" in system_content
    assert "Data Engineering" in system_content
    assert "DevOps / SRE" in system_content
    assert "Compound Responsibilities" in system_content
