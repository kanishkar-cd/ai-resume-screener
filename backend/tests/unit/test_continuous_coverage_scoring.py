import pytest
from app.schemas.matching import MatchStatus, MatchMethod, MatchVerdict, LLMVerdict, LLMVerdictBatch, Requirement, RequirementKind
from app.services.matching_service import _parse_llm_batch_response
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService


def test_parse_llm_batch_response_both_formats():
    req = Requirement(requirement_id="req_1", kind=RequirementKind.SKILL, text="Python programming", required=True)
    
    # 1. Standard batch format
    batch_json = {
        "verdicts": [
            {
                "requirement_id": "req_1",
                "sub_claims": ["Python syntax", "Object-oriented programming"],
                "sub_claim_evidence": [
                    {"claim": "Python syntax", "evidence_level": "direct", "note": "Used Python for 3 years"},
                    {"claim": "Object-oriented programming", "evidence_level": "adjacent", "note": "Built classes in Java"}
                ],
                "coverage_score": 0.8,
                "importance": "critical",
                "reasoning": "Strong python experience with OOP foundations."
            }
        ]
    }
    parsed = _parse_llm_batch_response(batch_json, [req])
    assert len(parsed.verdicts) == 1
    assert parsed.verdicts[0].coverage_score == 0.8
    assert parsed.verdicts[0].importance == "critical"
    assert len(parsed.verdicts[0].sub_claims) == 2

    # 2. Single object format
    single_json = {
        "sub_claims": ["microservices", "REST APIs"],
        "sub_claim_evidence": [
            {"claim": "microservices", "evidence_level": "adjacent", "note": "monolith modularization"},
            {"claim": "REST APIs", "evidence_level": "direct", "note": "FastAPI endpoints"}
        ],
        "coverage_score": 0.6,
        "importance": "important",
        "reasoning": "Direct REST API experience with transferable microservices skills."
    }
    parsed_single = _parse_llm_batch_response(single_json, [req])
    assert len(parsed_single.verdicts) == 1
    assert parsed_single.verdicts[0].requirement_id == "req_1"
    assert parsed_single.verdicts[0].coverage_score == 0.6
    assert parsed_single.verdicts[0].importance == "important"


def test_importance_weighted_skills_and_responsibilities():
    service = ComponentScoringService()
    
    # Candidate with 2 skills:
    # Skill 1: critical (wt 3), coverage 1.0 (Tier 1 exact match shortcut)
    # Skill 2: important (wt 2), coverage 0.5 (partial match)
    # Expected weighted score: (1.0*3 + 0.5*2) / (3+2) = 4.0 / 5.0 = 80.0%
    skill_verdicts = [
        MatchVerdict(
            requirement_id="skill:1",
            requirement_text="Python",
            kind=RequirementKind.SKILL,
            status=MatchStatus.MATCHED,
            confidence=1.0,
            coverage=1.0,
            coverage_score=1.0,
            importance="critical",
            method=MatchMethod.EXACT,
            sub_claims=["Python"],
            sub_claim_evidence=[{"claim": "Python", "evidence_level": "direct", "note": "exact"}]
        ),
        MatchVerdict(
            requirement_id="skill:2",
            requirement_text="AWS",
            kind=RequirementKind.SKILL,
            status=MatchStatus.PARTIALLY_MATCHED,
            confidence=0.85,
            coverage=0.5,
            coverage_score=0.5,
            importance="important",
            method=MatchMethod.LLM_CONFIRMED,
            sub_claims=["EC2", "S3"],
            sub_claim_evidence=[
                {"claim": "EC2", "evidence_level": "none", "note": "missing"},
                {"claim": "S3", "evidence_level": "direct", "note": "used S3"}
            ]
        ),
    ]

    # Responsibilities:
    # Resp 1: critical (wt 3), coverage 0.8
    # Resp 2: minor (wt 1), coverage 0.4
    # Expected weighted score: (0.8*3 + 0.4*1) / (3+1) = (2.4 + 0.4) / 4 = 2.8 / 4 = 70.0%
    resp_verdicts = [
        MatchVerdict(
            requirement_id="responsibility:1",
            requirement_text="Design REST APIs",
            kind=RequirementKind.RESPONSIBILITY,
            status=MatchStatus.MATCHED,
            confidence=0.9,
            coverage=0.8,
            coverage_score=0.8,
            importance="critical",
            method=MatchMethod.LLM_CONFIRMED,
            sub_claims=["API Design", "Scalability"],
            sub_claim_evidence=[
                {"claim": "API Design", "evidence_level": "direct", "note": "Designed 10+ endpoints"},
                {"claim": "Scalability", "evidence_level": "adjacent", "note": "Used Redis cache"}
            ]
        ),
        MatchVerdict(
            requirement_id="responsibility:2",
            requirement_text="Mentor junior developers",
            kind=RequirementKind.RESPONSIBILITY,
            status=MatchStatus.PARTIALLY_MATCHED,
            confidence=0.7,
            coverage=0.4,
            coverage_score=0.4,
            importance="minor",
            method=MatchMethod.LLM_CONFIRMED,
            sub_claims=["Mentoring", "Code reviews"],
            sub_claim_evidence=[
                {"claim": "Code reviews", "evidence_level": "direct", "note": "Regular reviewer"},
                {"claim": "Mentoring", "evidence_level": "none", "note": "No direct reports"}
            ]
        ),
    ]

    class FakeJob:
        skills = ["Python", "AWS"]
        required_skills = ["Python", "AWS"]
        preferred_skills = []
        responsibilities = ["Design REST APIs", "Mentor junior developers"]

    class FakeResume:
        skills = ["Python"]
        experience = []
        education = []
        projects = []
        certifications = []

    res = service.score(
        resume=FakeResume(),
        job=FakeJob(),
        config=None,
        match_verdicts=[*skill_verdicts, *resp_verdicts],
    )

    # 1. Skills score check: 80.0%
    assert res.skills.score == 80.0
    # 2. Responsibilities score check: 70.0%
    assert res.responsibilities.score == 70.0

    # In the 50/50 model:
    # Skills out of 50 = 80.0 * 0.50 = 40.0
    # Resp out of 50 = 70.0 * 0.50 = 35.0
    # Overall score = 40.0 + 35.0 = 75.0%
    _, _, final_score, effective_weights = WeightCalculationService.calculate(
        res, config=None, applicable_categories={"required_skills", "responsibilities"}
    )
    assert final_score == 75.0
    assert effective_weights["required_skills"] == 50.0
    assert effective_weights["responsibilities"] == 50.0


def test_zero_skills_safeguard_with_high_responsibilities():
    class FakeScores:
        class Comp:
            def __init__(self, s):
                self.score = s
                self.matched_items = ["a"] if s > 0 else []
                self.missing_items = [] if s > 0 else ["a"]
                self.explanation = ""
        skills = Comp(0.0)
        responsibilities = Comp(100.0)
        preferred_skills = Comp(0.0)
        certifications = Comp(0.0)
        experience = Comp(0.0)
        education = Comp(0.0)
        projects = Comp(0.0)
        languages = Comp(0.0)

    # Candidate has 0% in required skills, 100% in responsibilities
    # 0 * 0.5 + 100 * 0.5 = 50% raw, but safeguard MUST cap it at 35%
    _, _, final_score, _ = WeightCalculationService.calculate(
        FakeScores(), config=None, applicable_categories={"required_skills", "responsibilities"}
    )
    assert final_score == 35.0
