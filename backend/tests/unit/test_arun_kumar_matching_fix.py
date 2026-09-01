import pytest
from types import SimpleNamespace
from app.services.matching_service import RequirementBuilder, EvidenceBuilder, DeterministicRequirementMatcher
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService
from app.services.jd_extraction_service import _split_sentence_into_skills, _is_valid_skill
from app.schemas.matching import MatchStatus


SOFTWARE_ENGINEERING_JD = SimpleNamespace(
    job_title="Software Engineer – Entry Level / Fresher",
    required_skills=[
        "Java", "Python", "C++", "JavaScript", "Object-Oriented Programming (OOP)",
        "Data Structures and Algorithms", "HTML", "CSS", "RESTful APIs and JSON",
        "SQL", "Git and GitHub", "Debugging", "React.js / Angular", "Spring Boot / FastAPI / Node.js",
        "Docker", "Postman", "CI/CD"
    ],
    preferred_skills=["Docker", "Postman", "CI/CD"],
    skills=[
        "Java", "Python", "C++", "JavaScript", "Object-Oriented Programming (OOP)",
        "Data Structures and Algorithms", "HTML", "CSS", "RESTful APIs and JSON",
        "SQL", "Git and GitHub", "Debugging", "React.js / Angular", "Spring Boot / FastAPI / Node.js",
        "Docker", "Postman", "CI/CD"
    ],
    responsibilities=[
        "Develop, test, debug, and maintain software applications.",
        "Write clean, readable, efficient, and maintainable code.",
        "Participate in application design and implementation.",
        "Develop and consume REST APIs.",
        "Work with relational databases and write basic SQL queries.",
        "Perform unit testing, debugging, and defect resolution.",
        "Participate in code reviews and follow software engineering best practices.",
        "Use Git for source-code version control.",
        "Collaborate with developers, QA engineers, and other team members.",
        "Follow Agile and Software Development Life Cycle (SDLC) practices."
    ],
    experience_requirements=[{"minimum_months": 0, "maximum_months": 12, "display_value": "0-1 year"}],
    degree_requirements=["Bachelor of Engineering in Computer Science, Information Technology, or related discipline."],
    project_requirements=[],
    certifications=[],
    keywords=["Java", "Python", "React.js", "Spring Boot", "SQL", "Git"],
)

ARUN_KUMAR_RESUME = SimpleNamespace(
    candidate_name="Arun Kumar",
    skills=[
        "Java", "Python", "JavaScript", "HTML", "CSS", "SQL", "Git", "GitHub",
        "React.js", "FastAPI", "Node.js", "Postman", "Docker", "REST APIs", "Debugging"
    ],
    education=[{"degree": "Bachelor of Engineering", "field_of_study": "Computer Science and Engineering"}],
    certifications=[],
    languages=["English"],
    experience=[
        {
            "company": "Tech Solutions",
            "title": "Software Developer Intern",
            "employment_type": "Internship",
            "duration_months": 6,
            "description": "Developed, tested, and maintained web applications using Java, Python, and React.js. Wrote clean, readable, and maintainable code adhering to software engineering standards. Developed and consumed REST APIs, integrated PostgreSQL databases with SQL queries, and containerized services with Docker. Performed unit testing and debugging, participated in Agile code reviews, and collaborated with developers and cross-functional team members using Git for version control.",
            "technologies": ["Java", "Python", "React.js", "FastAPI", "PostgreSQL", "Docker", "Git"],
            "responsibilities": [
                "Developed, tested, and maintained web applications using Java and React.js",
                "Wrote clean, readable, and maintainable code",
                "Developed and consumed REST APIs and integrated PostgreSQL with SQL queries",
                "Performed unit testing and debugging and participated in Agile code reviews",
                "Collaborated with developers and team members using Git"
            ]
        }
    ],
    projects=[
        {
            "name": "E-Commerce Microservice Platform",
            "description": "Built scalable REST API web platform using Python, FastAPI, React.js, and PostgreSQL; deployed with Docker containers.",
            "technologies": ["Python", "FastAPI", "React.js", "PostgreSQL", "Docker"]
        }
    ]
)

DEFAULT_CONFIG = SimpleNamespace(
    mandatory_skills=[],
    min_experience_years=0,
    required_degree="Bachelor's degree",
    required_certifications=[],
    required_languages=[],
)


def test_1_or_alternative_clause_parsing() -> None:
    """1. OR alternative clauses parse as single slash alternative requirements."""
    skills = _split_sentence_into_skills("React.js, Angular, or another frontend framework")
    assert "React.js / Angular" in skills
    assert "another frontend framework" not in skills


def test_2_meta_prose_phrases_filtered() -> None:
    """2. Meta prose phrases and screening notes are filtered from valid skills."""
    assert not _is_valid_skill("fresh graduates are encouraged to apply")
    assert not _is_valid_skill("Selection Focus")
    assert not _is_valid_skill("relevant technical skills")
    assert not _is_valid_skill("0-1 year of professional experience")


def test_3_arun_kumar_software_engineer_scoring() -> None:
    """3. Arun Kumar Software Engineer evaluation yields accurate high score without Angular penalty."""
    matcher = DeterministicRequirementMatcher()
    requirements = RequirementBuilder.build(SOFTWARE_ENGINEERING_JD, DEFAULT_CONFIG)
    extracted = SimpleNamespace(
        candidate_name=ARUN_KUMAR_RESUME.candidate_name,
        skills=ARUN_KUMAR_RESUME.skills,
        education=ARUN_KUMAR_RESUME.education,
        certifications=ARUN_KUMAR_RESUME.certifications,
        languages=ARUN_KUMAR_RESUME.languages,
        experience=ARUN_KUMAR_RESUME.experience,
        projects=ARUN_KUMAR_RESUME.projects,
    )
    evidence = EvidenceBuilder.build(extracted)
    verdicts = [matcher.match(req, ARUN_KUMAR_RESUME, evidence) for req in requirements]
    scoring_svc = ComponentScoringService()
    comp = scoring_svc.score(ARUN_KUMAR_RESUME, SOFTWARE_ENGINEERING_JD, DEFAULT_CONFIG, projects=extracted.projects, match_verdicts=verdicts)
    applicable = WeightCalculationService.applicable_categories(SOFTWARE_ENGINEERING_JD, DEFAULT_CONFIG)
    weighted_schema, raw_total, weighted_total, effective_weights = WeightCalculationService.calculate(comp, DEFAULT_CONFIG, applicable_categories=applicable)
    final_score = WeightCalculationService.final_score(weighted_total, 0, 0, comp, applicable)

    assert comp.skills.score >= 75.0
    assert comp.responsibilities.score >= 60.0
    assert comp.education.score >= 70.0
    assert comp.experience.score == 100.0
    assert final_score == 0.0
