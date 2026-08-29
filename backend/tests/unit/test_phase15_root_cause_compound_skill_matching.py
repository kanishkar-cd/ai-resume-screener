import pytest
from types import SimpleNamespace

from app.schemas.matching import (
    Evidence, MatchMethod, MatchStatus, MatchVerdict, Requirement, RequirementKind,
)
from app.services.matching_service import (
    DeterministicRequirementMatcher, EvidenceBuilder, HybridMatchingService,
)
from app.services.scoring.component_scoring_service import ComponentScoringService


def test_jaishree_sql_and_database_concepts_matches_sql_candidate():
    """Verifies candidate Jaishree with SQL/database experience matches compound SQL requirement."""
    matcher = DeterministicRequirementMatcher()
    
    # JD requirement: Basic SQL and database concepts
    req_sql = Requirement(
        requirement_id="skill:1",
        kind=RequirementKind.SKILL,
        text="Basic SQL and database concepts",
    )
    
    # Candidate with SQL skill & relational database responsibility
    resume = SimpleNamespace(
        skills=["Java", "SQL", "HTML", "CSS", "JavaScript"],
        education=[{"degree": "B.Tech", "field_of_study": "Information Technology"}],
        certifications=[],
        languages=["English"],
        experience=[
            {
                "title": "Junior Developer",
                "company": "Tech Corp",
                "description": "Work with relational databases and write basic SQL queries for data management.",
                "responsibilities": ["Work with relational databases and write basic SQL queries."],
            }
        ],
        projects=[],
    )
    extracted = SimpleNamespace(
        candidate_name="JAISHREE Y",
        skills=resume.skills,
        education=resume.education,
        certifications=resume.certifications,
        languages=resume.languages,
        experience=resume.experience,
        projects=resume.projects,
    )
    evidence = EvidenceBuilder.build(extracted)

    verdict_sql = matcher.match(req_sql, resume, evidence)
    assert verdict_sql.status == MatchStatus.MATCHED
    assert verdict_sql.method in {MatchMethod.EXACT, MatchMethod.ALIAS}


def test_mysql_or_postgresql_matches_via_category_or_relational_database():
    """Verifies alternative / category requirement 'MySQL or PostgreSQL' matches candidate with SQL/relational DB."""
    matcher = DeterministicRequirementMatcher()
    
    req_db = Requirement(
        requirement_id="skill:2",
        kind=RequirementKind.SKILL,
        text="MySQL or PostgreSQL",
    )
    
    # Candidate who has PostgreSQL in skills
    resume_pg = SimpleNamespace(skills=["PostgreSQL", "Java"], certifications=[], projects=[], experience=[])
    evidence_pg = [Evidence(evidence_id="skills:1", kind="skills", text="PostgreSQL", canonical_terms=["PostgreSQL"])]
    v_pg = matcher.match(req_db, resume_pg, evidence_pg)
    assert v_pg.status == MatchStatus.MATCHED

    # Candidate who has SQL in skills
    resume_sql = SimpleNamespace(skills=["SQL", "Python"], certifications=[], projects=[], experience=[])
    evidence_sql = [Evidence(evidence_id="skills:1", kind="skills", text="SQL", canonical_terms=["SQL"])]
    v_sql = matcher.match(req_db, resume_sql, evidence_sql)
    assert v_sql.status == MatchStatus.MATCHED


def test_qualifiers_and_conjunctions_stripped_and_matched():
    """Verifies adjectives/qualifiers like 'Strong programming fundamentals in Java' match 'Java'."""
    matcher = DeterministicRequirementMatcher()
    
    req_java = Requirement(
        requirement_id="skill:1",
        kind=RequirementKind.SKILL,
        text="Strong programming fundamentals in Java",
    )
    resume = SimpleNamespace(skills=["Java", "C++"], certifications=[], projects=[], experience=[])
    evidence = [Evidence(evidence_id="skills:1", kind="skills", text="Java, C++", canonical_terms=["Java", "C++"])]
    
    v = matcher.match(req_java, resume, evidence)
    assert v.status == MatchStatus.MATCHED
    assert v.method in {MatchMethod.EXACT, MatchMethod.ALIAS}


def test_conjunction_with_secondary_concepts():
    """Verifies compound skills with meta-concepts (e.g. 'RESTful APIs and JSON', 'software testing and debugging') match."""
    matcher = DeterministicRequirementMatcher()
    
    req_rest = Requirement(
        requirement_id="skill:1",
        kind=RequirementKind.SKILL,
        text="RESTful APIs and JSON",
    )
    resume_rest = SimpleNamespace(skills=["REST APIs", "Python"], certifications=[], projects=[], experience=[])
    evidence_rest = [Evidence(evidence_id="skills:1", kind="skills", text="REST APIs", canonical_terms=["REST APIs"])]
    v_rest = matcher.match(req_rest, resume_rest, evidence_rest)
    assert v_rest.status == MatchStatus.MATCHED

    req_test = Requirement(
        requirement_id="skill:2",
        kind=RequirementKind.SKILL,
        text="software testing and debugging",
    )
    resume_test = SimpleNamespace(skills=["Testing", "Python"], certifications=[], projects=[], experience=[])
    evidence_test = [Evidence(evidence_id="skills:1", kind="skills", text="Testing", canonical_terms=["Testing"])]
    v_test = matcher.match(req_test, resume_test, evidence_test)
    assert v_test.status == MatchStatus.MATCHED


def test_component_scoring_service_concept_matching_enhanced():
    """Verifies ComponentScoringService directly scores compound requirements accurately."""
    scoring = ComponentScoringService()
    
    resume = SimpleNamespace(
        skills=["Java", "SQL", "HTML", "CSS", "JavaScript"],
        certifications=[],
        languages=["English"],
        experience=[
            {
                "title": "Software Engineer",
                "company": "Tech Corp",
                "description": "Work with relational databases and write basic SQL queries.",
                "responsibilities": ["Work with relational databases and write basic SQL queries."],
            }
        ],
        projects=[],
        education=[{"degree": "B.Tech", "field_of_study": "Computer Science"}],
    )
    job = SimpleNamespace(
        required_skills=["Strong programming fundamentals in Java", "Basic SQL and database concepts", "MySQL or PostgreSQL"],
        preferred_skills=[],
        responsibilities=["Work with relational databases and write basic SQL queries"],
        degree_requirements=[],
        experience_requirements=[],
    )
    config = SimpleNamespace(
        mandatory_skills=[],
        min_experience_years=0,
        required_degree=None,
        required_certifications=[],
        required_languages=[],
    )

    result = scoring.score(resume, job, config)
    # Java, SQL/database, and MySQL/PostgreSQL must all be recognized
    assert result.skills.score == 100.0
    assert len(result.skills.matched_items) == 3
    assert result.responsibilities.score == 100.0
