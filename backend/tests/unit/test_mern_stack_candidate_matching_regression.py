import pytest
from types import SimpleNamespace
from app.schemas.matching import RequirementKind, Requirement, MatchStatus, MatchMethod
from app.services.matching_service import RequirementBuilder, EvidenceBuilder, DeterministicRequirementMatcher
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.bonus_service import BonusService
from app.services.scoring.weight_calculation_service import WeightCalculationService


MERN_STACK_JD_TEXT = """
Job Type: Full-Time Experience: 5–8 Years Location: Chennai / Hybrid
About the Role
We are looking for a Senior MERN Stack Developer to design, develop, and maintain scalable web applications.
Key Responsibilities
• Design and develop scalable applications using MongoDB, Express.js, React.js, and Node.js.
• Build reusable, responsive, and high-performance React components and user interfaces.
• Develop secure RESTful APIs and integrate third-party services.
• Design efficient MongoDB schemas, indexes, queries, and aggregation pipelines.
• Implement authentication, authorization, validation, error handling, and logging.
• Review code, troubleshoot production issues, and improve application performance.
• Write unit and integration tests and maintain CI/CD pipelines.
• Collaborate with product, UI/UX, QA, and engineering teams.
• Mentor junior developers and contribute to technical design and architecture decisions.
Required Skills
Frontend: React.js, JavaScript/TypeScript, HTML5, CSS3, responsive design, state management.
Backend: Node.js, Express.js, REST APIs, authentication, authorization, asynchronous programming.
Database: MongoDB, schema design, indexing, aggregation, query optimization.
Engineering: Git, GitHub/GitLab, testing, debugging, clean code, API documentation.
Preferred Skills
Next.js, TypeScript, Redux Toolkit, Redis, Docker, AWS, GraphQL, CI/CD, microservices, WebSockets, Jest, React Testing Library.
Education
Bachelor’s degree in Computer Science, Information Technology, Engineering, or a related field.
"""


def test_mern_stack_jd_matching_and_scoring_for_all_candidates() -> None:
    # 1. Build JD structure
    req_skills = [
        "React.js", "JavaScript/TypeScript", "HTML5", "CSS3", "responsive design", "state management",
        "Node.js", "Express.js", "REST APIs", "authentication", "authorization", "asynchronous programming",
        "MongoDB", "schema design", "indexing", "aggregation", "query optimization",
        "Git", "GitHub/GitLab", "testing", "debugging", "clean code", "API documentation"
    ]
    pref_skills = [
        "Next.js", "TypeScript", "Redux Toolkit", "Redis", "Docker", "AWS",
        "GraphQL", "CI/CD", "microservices", "WebSockets", "Jest", "React Testing Library"
    ]
    job = SimpleNamespace(
        job_title="Senior MERN Stack Developer",
        required_skills=req_skills,
        preferred_skills=pref_skills,
        skills=[*req_skills, *pref_skills],
        experience_requirements=[{"minimum_months": 60, "maximum_months": 96}],
        degree_requirements=["Bachelor's degree in Computer Science, Information Technology, Engineering, or a related field."],
        keywords=["MERN Stack", "React.js", "Node.js", "MongoDB", "Express.js", "AWS", "Docker"],
        responsibilities=[
            "Design and develop scalable applications using MongoDB, Express.js, React.js, and Node.js.",
            "Build reusable, responsive, and high-performance React components and user interfaces.",
            "Develop secure RESTful APIs and integrate third-party services.",
        ]
    )
    config = SimpleNamespace(
        mandatory_skills=[],
        min_experience_years=5,
        required_degree="Bachelor's degree",
        required_certifications=[],
        required_languages=[],
    )

    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()

    # -------------------------------------------------------------
    # Candidate 1: Arjun Kumar
    # Profile: Python, FastAPI, REST APIs, PostgreSQL, Redis, Docker, Git, React, TypeScript
    # -------------------------------------------------------------
    arjun_resume = SimpleNamespace(
        skills=["Python", "FastAPI", "REST APIs", "PostgreSQL", "Redis", "Docker", "Git", "React", "TypeScript"],
        education=[{"degree": "B.E.", "field_of_study": "Computer Science and Engineering"}],
        certifications=["AWS Cloud Practitioner"],
        languages=[],
        experience=[
            {
                "company": "TechNova Solutions",
                "title": "Software Engineer",
                "duration_months": 42,
                "description": "Developed FastAPI REST services, PostgreSQL data models and Redis-backed application workflows. Built React/TypeScript interfaces and integrated third-party APIs.",
                "technologies": ["FastAPI", "PostgreSQL", "Redis", "React", "TypeScript", "REST APIs"],
                "responsibilities": ["Developed FastAPI REST services", "Built React/TypeScript interfaces", "integrated third-party APIs"],
            }
        ],
        projects=[],
    )
    arjun_extracted = SimpleNamespace(
        candidate_name="Arjun Kumar",
        skills=arjun_resume.skills,
        education=arjun_resume.education,
        certifications=arjun_resume.certifications,
        languages=[],
        experience=arjun_resume.experience,
        projects=[],
    )
    arjun_evidence = EvidenceBuilder.build(arjun_extracted)

    # Check Arjun Matches
    v_react = matcher.match(Requirement(requirement_id="skill:1", kind=RequirementKind.SKILL, text="React.js"), arjun_resume, arjun_evidence)
    assert v_react.status == MatchStatus.MATCHED

    v_js_ts = matcher.match(Requirement(requirement_id="skill:2", kind=RequirementKind.SKILL, text="JavaScript/TypeScript"), arjun_resume, arjun_evidence)
    assert v_js_ts.status == MatchStatus.MATCHED  # Matches via TypeScript

    v_rest = matcher.match(Requirement(requirement_id="skill:3", kind=RequirementKind.SKILL, text="REST APIs"), arjun_resume, arjun_evidence)
    assert v_rest.status == MatchStatus.MATCHED

    v_git = matcher.match(Requirement(requirement_id="skill:4", kind=RequirementKind.SKILL, text="Git"), arjun_resume, arjun_evidence)
    assert v_git.status == MatchStatus.MATCHED

    # Component Scores for Arjun
    arjun_scores = scoring_svc.score(arjun_resume, job, config, arjun_resume.projects)
    assert "React" in arjun_scores.skills.matched_items or "React.js" in arjun_scores.skills.matched_items
    assert "Git" in arjun_scores.skills.matched_items
    assert "REST APIs" in arjun_scores.skills.matched_items or "REST API" in arjun_scores.skills.matched_items

    # -------------------------------------------------------------
    # Candidate 2: Ravi Menon (Full-stack MERN with 5 years experience)
    # Profile: React, Node.js, Express, MongoDB, Git, HTML, CSS, JavaScript, REST API, Docker, AWS
    # -------------------------------------------------------------
    ravi_resume = SimpleNamespace(
        skills=["React", "Node.js", "Express", "MongoDB", "Git", "HTML", "CSS", "JavaScript", "REST API", "Docker", "AWS"],
        education=[{"degree": "Bachelor of Engineering", "field_of_study": "Computer Science"}],
        certifications=[],
        languages=[],
        experience=[
            {
                "company": "FullStack Solutions",
                "title": "Senior Web Developer",
                "duration_months": 60,
                "description": "Developed scalable MERN web applications using React.js, Node.js, Express.js and MongoDB. Built responsive interfaces with HTML5 and CSS3. Automated CI/CD pipelines and unit testing.",
                "technologies": ["React", "Node.js", "Express", "MongoDB", "Git", "HTML", "CSS", "JavaScript", "REST API", "Docker", "AWS"],
                "responsibilities": ["Design and develop scalable applications using MongoDB, Express.js, React.js, and Node.js"],
            }
        ],
        projects=[{"name": "E-Commerce Platform", "technologies": ["React", "Node.js", "MongoDB"], "description": "Built full stack MERN application"}],
    )
    ravi_extracted = SimpleNamespace(
        candidate_name="Ravi Menon",
        skills=ravi_resume.skills,
        education=ravi_resume.education,
        certifications=ravi_resume.certifications,
        languages=[],
        experience=ravi_resume.experience,
        projects=ravi_resume.projects,
    )
    ravi_evidence = EvidenceBuilder.build(ravi_extracted)

    # Check Ravi Matches: HTML5, CSS3, Git, Node.js, Express.js, MongoDB, React.js, REST APIs
    for skill_name in ["React.js", "JavaScript/TypeScript", "HTML5", "CSS3", "Node.js", "Express.js", "REST APIs", "MongoDB", "Git"]:
        v = matcher.match(Requirement(requirement_id=f"skill:{skill_name}", kind=RequirementKind.SKILL, text=skill_name), ravi_resume, ravi_evidence)
        assert v.status == MatchStatus.MATCHED, f"Ravi failed to match: {skill_name}"

    ravi_scores = scoring_svc.score(ravi_resume, job, config, ravi_resume.projects)
    assert ravi_scores.skills.score >= 39.0  # Matches 9+ out of 23 required skills

    ravi_bonus, ravi_bonus_items = BonusService.calculate(ravi_resume, job, config, ravi_scores)
    assert ravi_bonus >= 4.0  # Docker, AWS matched

    # -------------------------------------------------------------
    # Candidate 3: Priya Sharma
    # Profile: Python, FastAPI, PostgreSQL, MongoDB, Docker, HTML, CSS, Jenkins, AWS, REST API
    # -------------------------------------------------------------
    priya_resume = SimpleNamespace(
        skills=["Python", "FastAPI", "PostgreSQL", "MongoDB", "Docker", "HTML", "CSS", "Jenkins", "AWS", "REST API"],
        education=[{"degree": "Bachelor of Technology", "field_of_study": "Information Technology"}],
        certifications=[],
        languages=[],
        experience=[
            {
                "company": "Innovate Tech",
                "title": "Backend Developer",
                "duration_months": 24,
                "description": "Developed REST API microservices using Python and FastAPI.",
                "technologies": ["Python", "FastAPI", "MongoDB", "REST API", "Docker", "AWS"],
                "responsibilities": ["Develop secure RESTful APIs and integrate third-party services"],
            }
        ],
        projects=[],
    )
    priya_extracted = SimpleNamespace(
        candidate_name="Priya Sharma",
        skills=priya_resume.skills,
        education=priya_resume.education,
        certifications=priya_resume.certifications,
        languages=[],
        experience=priya_resume.experience,
        projects=[],
    )
    priya_evidence = EvidenceBuilder.build(priya_extracted)

    # Priya must match HTML5 (via HTML), CSS3 (via CSS), REST APIs (via REST API), MongoDB (via MongoDB)
    for req_name in ["HTML5", "CSS3", "REST APIs", "MongoDB"]:
        v = matcher.match(Requirement(requirement_id=f"skill:{req_name}", kind=RequirementKind.SKILL, text=req_name), priya_resume, priya_evidence)
        assert v.status == MatchStatus.MATCHED, f"Priya failed to match: {req_name}"

    # Priya must NOT match React.js, Node.js, Express.js (genuinely absent)
    for unavail in ["React.js", "Node.js", "Express.js"]:
        v_un = matcher.match(Requirement(requirement_id=f"skill:{unavail}", kind=RequirementKind.SKILL, text=unavail), priya_resume, priya_evidence)
        assert v_un.status == MatchStatus.NO_MATCH, f"Priya should not match: {unavail}"

    priya_scores = scoring_svc.score(priya_resume, job, config, priya_resume.projects)
    assert priya_scores.skills.score >= 17.0  # Matches 4 of 23 required skills

    priya_bonus, priya_bonus_items = BonusService.calculate(priya_resume, job, config, priya_scores)
    assert priya_bonus >= 4.0  # Docker, AWS matched
