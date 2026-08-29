import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, GroqMatchEvaluator, HybridMatchingService,
)
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService


def test_phase2_case_a_strong_mern():
    """Case A: 'Build and maintain REST APIs using Node.js and Express.js.' vs 'Developed RESTful APIs using Node.js and Express.' -> MATCHED (100%)."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Build and maintain REST APIs using Node.js and Express.js.",
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="project:1",
            kind="project",
            text="Developed RESTful APIs using Node.js and Express for user management.",
            canonical_terms=["Node.js", "Express"],
        )
    ]
    v = matcher.match(req, resume, evidence)
    assert v.status == MatchStatus.MATCHED
    assert v.coverage >= 0.75
    assert len(v.matched_concepts) >= 3


def test_phase2_case_b_distributed_evidence_across_bullets():
    """Case B: Evidence distributed across multiple project/experience bullets aggregates cleanly."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Build and maintain REST APIs using Node.js and Express.js.",
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="project:1",
            kind="project",
            text="Developed REST APIs using Node.js for high-volume transactions.",
            canonical_terms=["Node.js", "REST APIs"],
        ),
        Evidence(
            evidence_id="experience:1",
            kind="experience",
            text="Built Express.js backend services and middleware.",
            canonical_terms=["Express.js"],
        ),
    ]
    v = matcher.match(req, resume, evidence)
    assert v.status == MatchStatus.MATCHED
    assert v.coverage >= 0.75
    assert "node.js" in v.matched_concepts
    assert "express.js" in v.matched_concepts


def test_phase2_case_c_different_backend_technology():
    """Case C: Java and Spring Boot does not receive Node.js + Express.js credit."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Build and maintain REST APIs using Node.js and Express.js.",
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="experience:1",
            kind="experience",
            text="Developed REST APIs using Java and Spring Boot with PostgreSQL.",
            canonical_terms=["Java", "Spring Boot", "REST APIs"],
        )
    ]
    v = matcher.match(req, resume, evidence)
    # Node.js and Express.js are missing, so it does not get full tech credit
    assert "node.js" in v.missing_concepts
    assert "express.js" in v.missing_concepts


def test_phase2_case_d_skill_only_no_false_positive():
    """Case D: Skill list alone with no project/experience blocks does not satisfy responsibility."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Develop MERN applications using React, Node.js, Express.js and MongoDB.",
    )
    resume = SimpleNamespace(skills=["React", "Node.js", "Express.js", "MongoDB"], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="skills:1",
            kind="skills",
            text="React, Node.js, Express.js, MongoDB",
            canonical_terms=["React", "Node.js", "Express.js", "MongoDB"],
        )
    ]
    v = matcher.match(req, resume, evidence)
    assert v.status in {MatchStatus.UNRESOLVED, MatchStatus.UNMATCHED, MatchStatus.NO_MATCH}
    assert v.coverage == 0.0


def test_phase2_case_e_mongodb():
    """Case E: 'Design and integrate MongoDB databases with Node.js applications.' vs 'Designed MongoDB schemas using Mongoose for a Node.js application.' -> MATCHED."""
    matcher = DeterministicRequirementMatcher()
    req = Requirement(
        requirement_id="responsibility:1",
        kind=RequirementKind.RESPONSIBILITY,
        text="Design and integrate MongoDB databases with Node.js applications.",
    )
    resume = SimpleNamespace(skills=[], projects=[], experience=[])
    evidence = [
        Evidence(
            evidence_id="project:1",
            kind="project",
            text="Designed MongoDB schemas using Mongoose for a Node.js application.",
            canonical_terms=["MongoDB", "Mongoose", "Node.js"],
        )
    ]
    v = matcher.match(req, resume, evidence)
    assert v.status == MatchStatus.MATCHED
    assert v.coverage >= 0.75
    assert "mongodb" in v.matched_concepts
    assert "node.js" in v.matched_concepts


def test_phase2_real_mern_candidates_regression():
    """Tests real MERN candidates against Senior MERN JD responsibilities."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    mern_resps = [
        "Design and develop scalable applications using MongoDB, Express.js, React.js, and Node.js.",
        "Build reusable, responsive, and high-performance React components and user interfaces.",
        "Develop secure RESTful APIs and integrate third-party services.",
    ]
    job = SimpleNamespace(
        required_skills=["React.js", "Node.js", "Express.js", "MongoDB", "REST APIs"],
        preferred_skills=["Docker", "AWS", "Redis"],
        responsibilities=mern_resps,
        degree_requirements=["Bachelor's degree in Computer Science"],
        experience_requirements=[{"minimum_months": 36}],
    )
    config = SimpleNamespace(min_experience_years=3)

    # 1. ASWIN SURIYA C (MERN Candidate)
    aswin_extracted = SimpleNamespace(
        candidate_name="Aswin Suriya C",
        skills=["React", "Node.js", "Express", "MongoDB", "JavaScript", "REST APIs"],
        experience=[{
            "title": "MERN Stack Developer",
            "company": "WebTech",
            "description": "Developed full-stack web applications using React.js and Node.js with Express backend. Designed MongoDB schemas and built RESTful APIs.",
            "technologies": ["React", "Node.js", "Express", "MongoDB", "REST APIs"],
            "responsibilities": ["Built RESTful APIs and React interfaces", "Designed MongoDB collections"],
        }],
        projects=[{
            "name": "E-Commerce App",
            "description": "Built responsive React user interfaces and integrated Node/Express REST APIs with MongoDB.",
            "technologies": ["React", "Node.js", "MongoDB", "Express"],
        }],
        education=[{"degree": "B.E.", "field_of_study": "CSE"}],
        certifications=[],
    )
    aswin_evidence = EvidenceBuilder.build(aswin_extracted)
    aswin_verdicts = [
        matcher.match(Requirement(requirement_id=f"responsibility:{i+1}", kind=RequirementKind.RESPONSIBILITY, text=r), aswin_extracted, aswin_evidence)
        for i, r in enumerate(mern_resps)
    ]
    aswin_scores = scoring_svc.score(aswin_extracted, job, config, match_verdicts=aswin_verdicts)
    # Aswin must receive high responsibility score (>= 75%)
    assert aswin_scores.responsibilities.score >= 75.0

    # 2. JAISHREE Y (MERN Candidate)
    jaishree_extracted = SimpleNamespace(
        candidate_name="Jaishree Y",
        skills=["React.js", "Node.js", "Express.js", "MongoDB", "REST API"],
        experience=[],
        projects=[
            {
                "name": "Social Media Platform",
                "description": "Developed full stack application using MongoDB, Express.js, React.js, and Node.js. Implemented user authentication and REST APIs.",
                "technologies": ["React.js", "Node.js", "Express.js", "MongoDB"],
            },
            {
                "name": "UI Component Library",
                "description": "Built reusable, responsive React components and user interfaces with Tailwind CSS.",
                "technologies": ["React.js", "JavaScript"],
            }
        ],
        education=[{"degree": "B.Tech", "field_of_study": "IT"}],
        certifications=[],
    )
    jaishree_evidence = EvidenceBuilder.build(jaishree_extracted)
    jaishree_verdicts = [
        matcher.match(Requirement(requirement_id=f"responsibility:{i+1}", kind=RequirementKind.RESPONSIBILITY, text=r), jaishree_extracted, jaishree_evidence)
        for i, r in enumerate(mern_resps)
    ]
    jaishree_scores = scoring_svc.score(jaishree_extracted, job, config, match_verdicts=jaishree_verdicts)
    assert jaishree_scores.responsibilities.score >= 75.0

    # 3. SRI GEETHANI R (MERN Candidate)
    geethani_extracted = SimpleNamespace(
        candidate_name="Sri Geethani R",
        skills=["React", "Node.js", "MongoDB", "JavaScript"],
        experience=[{
            "title": "Full Stack Intern",
            "company": "DevSolutions",
            "description": "Built responsive React components and integrated RESTful APIs using Node.js and MongoDB.",
            "technologies": ["React", "Node.js", "MongoDB"],
            "responsibilities": ["Created UI components", "Managed MongoDB database queries"],
        }],
        projects=[],
        education=[{"degree": "B.E.", "field_of_study": "CSE"}],
        certifications=[],
    )
    geethani_evidence = EvidenceBuilder.build(geethani_extracted)
    geethani_verdicts = [
        matcher.match(Requirement(requirement_id=f"responsibility:{i+1}", kind=RequirementKind.RESPONSIBILITY, text=r), geethani_extracted, geethani_evidence)
        for i, r in enumerate(mern_resps)
    ]
    geethani_scores = scoring_svc.score(geethani_extracted, job, config, match_verdicts=geethani_verdicts)
    assert geethani_scores.responsibilities.score >= 60.0

    # 4. NON-MATCHING JAVA CANDIDATE
    java_extracted = SimpleNamespace(
        candidate_name="Java Candidate",
        skills=["Java", "Spring Boot", "PostgreSQL", "Hibernate"],
        experience=[{
            "title": "Java Developer",
            "company": "Enterprise Corp",
            "description": "Developed backend microservices using Java and Spring Boot with PostgreSQL. Created batch jobs.",
            "technologies": ["Java", "Spring Boot", "PostgreSQL"],
            "responsibilities": ["Managed PostgreSQL schemas"],
        }],
        projects=[],
        education=[{"degree": "B.Tech", "field_of_study": "CSE"}],
        certifications=[],
    )
    java_evidence = EvidenceBuilder.build(java_extracted)
    java_verdicts = [
        matcher.match(Requirement(requirement_id=f"responsibility:{i+1}", kind=RequirementKind.RESPONSIBILITY, text=r), java_extracted, java_evidence)
        for i, r in enumerate(mern_resps)
    ]
    java_scores = scoring_svc.score(java_extracted, job, config, match_verdicts=java_verdicts)
    # Java candidate must receive low responsibility score (< 40%)
    assert java_scores.responsibilities.score <= 35.0
