import pytest
from app.services.affinda_mapper import map_affinda_resume
from app.services.normalizers.resume_normalizer import ResumeNormalizer
from app.services.extractors.resume_extractor import ResumeExtractor


def test_resume_profile_fixes_all_6_issues():
    source_text = """
    JEGADHEES J
    Phone: +91 98765 43210
    Email: jegadhees@example.com

    SKILLS
    React.js, Node.js, Express.js, MongoDB, REST API, Next.js, C, HTML, CSS, JavaScript, MySQL, Git, Postman, Playwright, DSA, OOP, DBMS

    EDUCATION
    B.Tech (CSBS) - Sri Eshwar College of Engineering - CGPA 8.4
    HSC - MVM Higher Secondary School
    SSLC - MVM Higher Secondary School

    CERTIFICATIONS
    Introduction to Python – Infosys SpringBoard
    Python for Data Science – Udemy
    SQL Basics – SkillRack
    Introduction to Tableau

    ACHIEVEMENTS
    LeetCode
    CodeChef
    HackerRank
    GeeksforGeeks
    NextGenHack Top 3 Winner
    Project Expo 3rd Place

    EXPERIENCE
    PQA Intern – Nimble Wireless, Private Ltd
    """

    payload = {
        "candidateName": {"firstName": "JEGADHEES", "familyName": "J"},
        "phoneNumber": [],
        "email": ["jegadhees@example.com"],
        "skill": [
            {"name": "React.js (Javascript Library)"},
            {"name": "Node.js (Javascript Library)"},
            {"name": "Express.js (Javascript Library)"},
            {"name": "MongoDB"},
            {"name": "Application Programming Interface (API)"},
            {"name": "Next.js"},
            {"name": "C (programming language)"},
            {"name": "HTML Scripting"},
            {"name": "Cascading Style Sheets (CSS)"},
            {"name": "JavaScript"},
            {"name": "MySQL"},
            {"name": "Git (Version Control System)"},
            {"name": "Postman"},
            {"name": "Playwright"},
            {"name": "Data Structures"},
            {"name": "Object-Oriented Programming (OOP)"},
            {"name": "DBMS"},
            {"name": "Proxy Statement"},
            {"name": "Celestial Navigation"},
            {"name": "Results Focused"},
            {"name": "Casting"},
            {"name": "Rendering"},
            {"name": "Management"},
            {"name": "Analytics"},
            {"name": "Retail Management"},
        ],
        "education": [
            {
                "educationAccreditation": "B.Tech (CSBS)",
                "educationOrganization": "Sri Eshwar College of Engineering",
                "educationMajor": ["Computer Science and Business Systems"]
            },
            {
                "educationAccreditation": "HSC, SSLC",
                "educationOrganization": "MVM Higher Secondary School",
            },
            {
                "educationAccreditation": "Introduction to Python",
                "educationOrganization": "Infosys SpringBoard",
            }
        ],
        "workExperience": [
            {
                "workExperienceJobTitle": "PQA Intern",
                "workExperienceOrganization": "Nimble Wireless, Private Ltd",
            }
        ],
        "project": [],
        "certification": [
            {"name": "Python for Data Science – Udemy"},
            {"name": "SQL Basics – SkillRack"},
            {"name": "Introduction to Tableau"}
        ]
    }

    extracted, normalized = map_affinda_resume(payload, "provider-id", source_text)

    # 1. Skills verification
    expected_tech_skills = ["React.js", "Node.js", "Express.js", "MongoDB", "REST API", "Next.js", "C", "HTML", "CSS", "JavaScript", "MySQL", "Git", "Postman", "Playwright", "DSA", "OOP", "DBMS"]
    for tech_skill in expected_tech_skills:
        assert tech_skill in extracted["skills"] or tech_skill in normalized["skills"], f"Missing skill: {tech_skill}"

    noise_skills = ["Proxy Statement", "Celestial Navigation", "Results Focused", "Casting", "Rendering", "Management", "Analytics", "Retail Management"]
    for noise in noise_skills:
        assert noise not in extracted["skills"], f"Unwanted noise skill extracted: {noise}"
        assert noise not in normalized["skills"], f"Unwanted noise skill normalized: {noise}"

    # 2. Education separation verification
    edu_degrees = [e["degree"] for e in extracted["education"]]
    assert "B.Tech (CSBS)" in edu_degrees
    assert "HSC" in edu_degrees
    assert "SSLC" in edu_degrees

    edu_orgs = [e["institution"] for e in extracted["education"]]
    assert "Sri Eshwar College of Engineering" in edu_orgs
    assert "MVM Higher Secondary School" in edu_orgs
    assert not any("Infosys" in (e.get("institution") or "") or "Python" in (e.get("degree") or "") for e in extracted["education"])

    # 3. Certifications mapping verification
    certs = extracted["certifications"]
    assert any("Introduction to Python" in c and "Infosys" in c for c in certs), "Missing Python Infosys certification"
    assert any("Python for Data Science" in c and "Udemy" in c for c in certs), "Missing Udemy certification"
    assert any("SQL Basics" in c and "SkillRack" in c for c in certs), "Missing SkillRack certification"
    assert any("Introduction to Tableau" in c for c in certs), "Missing Tableau certification"

    # 4. Achievements verification
    achievements = extracted["achievements"]
    assert "LeetCode" in achievements
    assert "CodeChef" in achievements
    assert "HackerRank" in achievements
    assert "GeeksforGeeks" in achievements
    assert "NextGenHack Top 3 Winner" in achievements
    assert "Project Expo 3rd Place" in achievements

    # 5. Experience verification
    exp_companies = [e["company"] for e in extracted["experience"]]
    exp_titles = [e["title"] or e["designation"] for e in extracted["experience"]]
    assert any("Nimble Wireless" in (c or "") for c in exp_companies), "Missing Nimble Wireless company"
    assert any("PQA Intern" in (t or "") for t in exp_titles), "Missing PQA Intern job title"

    # 6. Contact phone verification
    assert extracted["phone"] is not None
    assert extracted["phone"] != "Not provided"
    assert "98765" in extracted["phone"] or "43210" in extracted["phone"]


def test_arun_kumar_resume_skill_extraction_filters_false_positives():
    source_text = """
    ARUN KUMAR
    Phone: +91 98765 12345
    Email: arunkumar@example.com

    TECHNICAL SKILLS
    Python, Java, JavaScript, C++, OOP, Data Structures and Algorithms,
    HTML, CSS, REST APIs, JSON, FastAPI, Spring Boot, Node.js,
    React, SQL, MySQL, PostgreSQL, Git, GitHub, Postman, Docker,
    Agile, SDLC, CI/CD, software testing, debugging

    EDUCATION
    B.Tech - Computer Science and Engineering
    SRM Institute of Science and Technology

    CERTIFICATIONS
    Python Programming
    SQL and Database Fundamentals
    Git and GitHub Fundamentals

    EXPERIENCE
    Software Engineering Intern
    Technology Solutions Pvt. Ltd.
    3 months

    PROJECTS
    AI Resume Screener
    Task Management Web Application
    Student Performance Analytics
    """

    payload = {
        "candidateName": {"firstName": "ARUN", "familyName": "KUMAR"},
        "email": ["arunkumar@example.com"],
        "phoneNumber": ["+91 98765 12345"],
        "skill": [
            {"name": "Python"}, {"name": "Java (programming language)"}, {"name": "JavaScript"},
            {"name": "C++"}, {"name": "Object-Oriented Programming (OOP)"},
            {"name": "Data Structures and Algorithms"}, {"name": "HTML Scripting"},
            {"name": "Cascading Style Sheets (CSS)"}, {"name": "Application Programming Interface (API)"},
            {"name": "JSON"}, {"name": "FastAPI"}, {"name": "Spring Boot"}, {"name": "Node.js (javascript library)"},
            {"name": "React.js (javascript library)"}, {"name": "SQL"}, {"name": "MySQL"}, {"name": "PostgreSQL"},
            {"name": "Git (version control system)"}, {"name": "GitHub"}, {"name": "Postman"}, {"name": "Docker"},
            {"name": "Agile"}, {"name": "SDLC"}, {"name": "CI/CD"}, {"name": "Software Testing"}, {"name": "Debugging"},
            # False positive noise items returned by third-party parser
            {"name": "Software Engineering"}, {"name": "Computer Science"}, {"name": "Engineering Analysis"},
            {"name": "Smartlist"}, {"name": "Branding"}, {"name": "Academic Support Services"},
            {"name": "Behavioral Health"}, {"name": "Stand-Up Comedy"}, {"name": "CATIA Certification"},
            {"name": "Management"}, {"name": "Communications"}
        ],
        "education": [
            {"educationAccreditation": "B.Tech", "educationOrganization": "SRM Institute of Science and Technology", "educationMajor": ["Computer Science and Engineering"]}
        ],
        "workExperience": [
            {"workExperienceJobTitle": "Software Engineering Intern", "workExperienceOrganization": "Technology Solutions Pvt. Ltd.", "workExperienceDescription": "3 months"}
        ],
        "project": [
            {"projectTitle": "AI Resume Screener"},
            {"projectTitle": "Task Management Web Application"},
            {"projectTitle": "Student Performance Analytics"}
        ]
    }

    extracted, normalized = map_affinda_resume(payload, "provider-arun", source_text)

    # Verify all 26 technical skills are extracted
    valid_skills = [
        "Python", "Java", "JavaScript", "C++", "Object-Oriented Programming",
        "Data Structures and Algorithms", "HTML", "CSS", "REST API", "JSON",
        "FastAPI", "Spring Boot", "Node.js", "React.js", "SQL", "MySQL",
        "PostgreSQL", "Git", "GitHub", "Postman", "Docker", "Agile", "SDLC",
        "CI/CD", "Software Testing", "Debugging"
    ]
    for skill in valid_skills:
        assert skill in extracted["skills"] or any(skill.casefold() in s.casefold() for s in extracted["skills"]), f"Missing valid skill in extracted: {skill}"
        assert skill in normalized["skills"] or any(skill.casefold() in s.casefold() for s in normalized["skills"]), f"Missing valid skill in normalized: {skill}"

    # Explicit check for the 5 key skills
    assert any(s.casefold() == "c++" for s in normalized["skills"]), "C++ missing in normalized skills"
    assert any(s.casefold() == "postman" for s in normalized["skills"]), "Postman missing in normalized skills"
    assert any(s.casefold() == "docker" for s in normalized["skills"]), "Docker missing in normalized skills"
    assert any(s.casefold() == "agile" for s in normalized["skills"]), "Agile missing in normalized skills"
    assert any(s.casefold() == "sdlc" for s in normalized["skills"]), "SDLC missing in normalized skills"

    # Verify C++ remains C++ and does not become C
    assert "C" not in extracted["skills"], "C++ improperly mapped to C"
    assert "C" not in normalized["skills"], "C++ improperly mapped to C"

    # Verify certifications fallback from source_text and are properly exposed in certifications field
    expected_certs = ["Python Programming", "SQL and Database Fundamentals", "Git and GitHub Fundamentals"]
    for cert in expected_certs:
        assert any(cert.casefold() in c.casefold() for c in extracted["certifications"]), f"Missing certification in extracted: {cert}"
        assert any(cert.casefold() in c.casefold() for c in normalized["certifications"]), f"Missing certification in normalized: {cert}"

    # Verify certifications are NOT misclassified into education
    edu_degrees_and_orgs = [f"{e.get('degree') or ''} {e.get('institution') or ''}".casefold() for e in normalized["education"]]
    for cert in expected_certs:
        assert not any(cert.casefold() in edu for edu in edu_degrees_and_orgs), f"Certification misclassified into education: {cert}"

    # Verify false positives, project titles, and soft skills are filtered from root skills
    false_positives = [
        "Software Engineering", "Computer Science", "Engineering Analysis",
        "Smartlist", "Branding", "Academic Support Services", "Behavioral Health",
        "Stand-Up Comedy", "CATIA Certification", "Management", "Communications",
        "Task Management", "Performance Analytics", "Parsing", "Information Extraction",
        "Data Processing", "Problem Solving", "Analytical Thinking", "Quick Learning", "Adaptability"
    ]
    for fp in false_positives:
        assert fp not in extracted["skills"], f"False positive skill permitted into extracted skills: {fp}"
        assert fp not in normalized["skills"], f"False positive skill permitted into normalized skills: {fp}"


def test_priya_sharma_data_engineer_resume_extraction():
    source_text = """
    PRIYA SHARMA
    Phone: +91 91234 56789
    Email: priyasharma@example.com

    TECHNICAL SKILLS
    Python, SQL, Java, ETL, ELT, Data Pipelines, Data Cleaning, Data Validation,
    Batch Processing, Apache Spark, PySpark, Apache Airflow, PostgreSQL, MySQL,
    MongoDB, AWS S3, Git, GitHub, Docker, Linux, REST APIs, JSON, CSV, Parquet,
    Data Structures and Algorithms, OOP, SDLC, Agile, Debugging

    CERTIFICATIONS
    Python for Data Engineering
    SQL and Relational Database Fundamentals
    Apache Spark Fundamentals

    EDUCATION
    B.Tech - Information Technology
    SRM Institute of Science and Technology

    EXPERIENCE
    Data Engineering Intern
    Tech Corp Pvt Ltd
    6 months

    PROJECTS
    Retail Sales Data Pipeline
    Airflow Data Warehouse Pipeline
    Customer Analytics Database
    """

    payload = {
        "candidateName": {"firstName": "PRIYA", "familyName": "SHARMA"},
        "email": ["priyasharma@example.com"],
        "phoneNumber": ["+91 91234 56789"],
        "skill": [
            {"name": "Python"}, {"name": "SQL"}, {"name": "Java"},
            {"name": "ETL"}, {"name": "ELT"}, {"name": "Data Pipelines"},
            {"name": "Data Cleaning"}, {"name": "Data Validation"}, {"name": "Batch Processing"},
            {"name": "Apache Spark"}, {"name": "PySpark"}, {"name": "Apache Airflow"},
            {"name": "PostgreSQL"}, {"name": "MySQL"}, {"name": "MongoDB"},
            {"name": "AWS S3"}, {"name": "Git"}, {"name": "GitHub"}, {"name": "Docker"},
            {"name": "Linux"}, {"name": "REST API"}, {"name": "JSON"}, {"name": "CSV"},
            {"name": "Parquet"}, {"name": "Data Structures and Algorithms"},
            {"name": "Object-Oriented Programming"}, {"name": "SDLC"}, {"name": "Agile"}, {"name": "Debugging"},
        ],
        "education": [
            {"educationAccreditation": "B.Tech", "educationOrganization": "SRM Institute of Science and Technology", "educationMajor": ["Information Technology"]},
            # Misclassified certification items from third-party parser
            {"educationAccreditation": "Python for Data Engineering", "educationOrganization": ""},
            {"educationAccreditation": "SQL and Relational Database Fundamentals", "educationOrganization": ""},
            {"educationAccreditation": "Apache Spark Fundamentals", "educationOrganization": ""}
        ],
        "workExperience": [
            {"workExperienceJobTitle": "Data Engineering Intern", "workExperienceOrganization": "Tech Corp Pvt Ltd"}
        ],
        "project": [
            {"projectTitle": "Retail Sales Data Pipeline", "technologies": ["Python", "PySpark", "PostgreSQL", "AWS S3", "Parquet"]},
            {"projectTitle": "Airflow Data Warehouse Pipeline", "technologies": ["Apache Airflow", "Python", "SQL"]},
            {"projectTitle": "Customer Analytics Database", "technologies": ["PostgreSQL", "SQL", "Python"]}
        ]
    }

    extracted, normalized = map_affinda_resume(payload, "provider-priya", source_text)

    # 1. Verify key Data Engineering technical skills
    required_de_skills = [
        "Python", "SQL", "Java", "ETL", "ELT", "Data Pipelines", "Data Cleaning",
        "Data Validation", "Batch Processing", "Apache Spark", "PySpark", "Apache Airflow",
        "PostgreSQL", "MySQL", "MongoDB", "AWS S3", "Git", "GitHub", "Docker", "Linux",
        "REST API", "JSON", "CSV", "Parquet", "Data Structures and Algorithms",
        "Object-Oriented Programming", "SDLC", "Agile", "Debugging"
    ]
    for skill in required_de_skills:
        assert any(skill.casefold() in s.casefold() for s in extracted["skills"]), f"Missing DE skill in extracted: {skill}"
        assert any(skill.casefold() in s.casefold() for s in normalized["skills"]), f"Missing DE skill in normalized: {skill}"

    # 2. Verify all 3 certifications are exposed in certifications field
    expected_certs = [
        "Python for Data Engineering",
        "SQL and Relational Database Fundamentals",
        "Apache Spark Fundamentals"
    ]
    for cert in expected_certs:
        assert any(cert.casefold() in c.casefold() for c in extracted["certifications"]), f"Missing certification in extracted: {cert}"
        assert any(cert.casefold() in c.casefold() for c in normalized["certifications"]), f"Missing certification in normalized: {cert}"

    # 3. Verify certifications are NOT in education
    edu_combined = [f"{e.get('degree') or ''} {e.get('institution') or ''}".casefold() for e in normalized["education"]]
    for cert in expected_certs:
        assert not any(cert.casefold() in edu for edu in edu_combined), f"Certification misclassified under education: {cert}"

    # 4. Verify project title domain noise terms are filtered from root skills
    project_noise = ["Sales", "Customer Analytics", "Business Metrics", "Data Extraction", "Retail Sales"]
    for noise in project_noise:
        assert noise not in extracted["skills"], f"Project noise permitted into extracted skills: {noise}"
        assert noise not in normalized["skills"], f"Project noise permitted into normalized skills: {noise}"


def test_stale_extraction_ruleset_version_freshness():
    # Simulate a stale extracted record created before ruleset 1.1.0 with misclassified education items
    class DummyExtracted:
        skills = ["Python", "SQL"]
        education = [
            {"degree": "B.Tech", "institution": "SRM Institute of Science and Technology", "field_of_study": "Computer Science"},
            {"degree": "Python for Data Engineering", "institution": ""},
            {"degree": "SQL and Relational Database Fundamentals", "institution": ""},
            {"degree": "Apache Spark Fundamentals", "institution": ""}
        ]
        experience = []
        projects = []
        companies = []
        certifications = []
        designation = "Data Engineer"
        location = None
        phone = "+919123456789"
        email = "test@example.com"
        languages = []
        raw_metadata = {
            "ruleset_version": "1.0.0",
            "affinda_normalized_profile": {
                "ruleset_version": "1.0.0",
                "skills": ["Python", "SQL"],
                "education": [
                    {"degree": "B.Tech", "institution": "SRM Institute of Science and Technology", "field_of_study": "Computer Science"},
                    {"degree": "Python for Data Engineering", "institution": ""},
                    {"degree": "SQL and Relational Database Fundamentals", "institution": ""},
                    {"degree": "Apache Spark Fundamentals", "institution": ""}
                ],
                "certifications": []
            }
        }

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(DummyExtracted())

    # 1. Certifications must be properly exposed under certifications
    assert len(normalized["certifications"]) == 3
    assert "Python for Data Engineering" in normalized["certifications"]
    assert "SQL and Relational Database Fundamentals" in normalized["certifications"]
    assert "Apache Spark Fundamentals" in normalized["certifications"]

    # 2. Education must only contain the academic degree
    assert len(normalized["education"]) == 1
    assert normalized["education"][0]["degree"] == "Bachelor of Technology"


def test_devops_cloud_resume_normalization():
    class DummyDevOps:
        skills = ["AWS", "AWS S3", "Docker", "Kubernetes", "Terraform", "Git"]
        education = [{"degree": "B.E.", "institution": "Anna University", "field_of_study": "Information Technology"}]
        experience = [{"company": "CloudCorp", "title": "DevOps Engineer", "description": "Managed AWS S3 and Kubernetes clusters for 6 months"}]
        projects = []
        certifications = ["AWS Certified Solutions Architect"]

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(DummyDevOps())

    assert "AWS" in normalized["skills"]
    assert "AWS S3" in normalized["skills"]
    assert "Docker" in normalized["skills"]
    assert "Kubernetes" in normalized["skills"]
    assert len(normalized["certifications"]) == 1
    assert "AWS Certified Solutions Architect" in normalized["certifications"]


def test_qa_testing_resume_normalization():
    class DummyQA:
        skills = ["Selenium", "Playwright", "Postman", "JUnit", "REST API", "Python"]
        education = [{"degree": "BCA", "institution": "Madras University", "field_of_study": "Computer Applications"}]
        experience = [{"company": "TestTech", "title": "QA Engineer", "description": "Automated testing with Selenium and Playwright for 1 year"}]
        projects = []
        certifications = ["ISTQB Certified Tester"]

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(DummyQA())

    assert "Selenium" in normalized["skills"]
    assert "Playwright" in normalized["skills"]
    assert "Postman" in normalized["skills"]
    assert "ISTQB Certified Tester" in normalized["certifications"]


def test_empty_projects_and_certifications():
    class DummyEmpty:
        skills = ["Python", "SQL"]
        education = [{"degree": "B.Tech", "institution": "IIT", "field_of_study": "CS"}]
        experience = []
        projects = []
        certifications = []

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(DummyEmpty())

    assert normalized["projects"] == []
    assert normalized["certifications"] == []
    assert len(normalized["education"]) == 1


def test_undated_explicit_experience_duration():
    class DummyUndated:
        skills = ["Python"]
        education = []
        experience = [{"company": "TechSol", "title": "Intern", "description": "Software Intern for 3 months"}]
        projects = []
        certifications = []

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(DummyUndated())

    assert normalized["total_experience_months"] == 3
    assert normalized["candidate_level"] == "FRESHER"


def test_cpp_vs_c_distinction():
    class DummyCpp:
        skills = ["C++", "C", "Python"]
        education = []
        experience = []
        projects = []
        certifications = []

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(DummyCpp())

    assert "C++" in normalized["skills"]
    assert "C" in normalized["skills"]
    assert normalized["skills"].count("C++") == 1
    assert normalized["skills"].count("C") == 1


def test_soft_skills_and_duplicate_aliases():
    class DummyDuplicates:
        skills = ["React.js", "React", "Node", "Node.js", "Github", "GitHub", "Problem Solving", "Communication"]
        education = []
        experience = []
        projects = []
        certifications = []

    normalizer = ResumeNormalizer()
    normalized = normalizer.normalize(DummyDuplicates())

    assert "React" in normalized["skills"]
    assert normalized["skills"].count("React") == 1
    assert "Node.js" in normalized["skills"]
    assert normalized["skills"].count("Node.js") == 1
    assert "GitHub" in normalized["skills"]
    assert normalized["skills"].count("GitHub") == 1
    assert "Problem Solving" not in normalized["skills"]
    assert "Communication" not in normalized["skills"]


def test_section_detection_variations():
    from app.services.pipeline.extraction_pipeline import segment_sections

    raw_resume = """
    PRIYA SHARMA
    priya@example.com | +919123456789 | Chennai, India

    TECHNICAL SKILLS:
    Python, SQL, PostgreSQL, Docker, AWS S3, Apache Spark, PySpark, Airflow

    ACADEMIC QUALIFICATIONS —
    B.Tech – Computer Science and Engineering
    SRM Institute of Science and Technology, 2026

    EXPERIENCE / INTERNSHIP:
    Data Engineering Intern – DataWorks Technologies | 4 months
    Built ETL pipelines using Python and Spark.

    PROJECTS & EXPERIENCE:
    Retail Sales Data Pipeline
    Airflow Data Warehouse Pipeline
    Customer Analytics Database

    COURSES & CERTIFICATIONS:
    Python for Data Engineering
    SQL and Relational Database Fundamentals
    Apache Spark Fundamentals
    """

    sections = segment_sections(raw_resume)
    assert "header" in sections
    assert "skills" in sections
    assert "education" in sections
    assert "experience" in sections
    assert "projects" in sections
    assert "certifications" in sections

    from app.services.extractors.resume_extractor import ResumeExtractor
    extracted = ResumeExtractor().extract(raw_resume)

    assert extracted["candidate_name"] == "PRIYA SHARMA"
    assert len(extracted["education"]) >= 1
    assert len(extracted["experience"]) >= 1
    assert len(extracted["projects"]) >= 3
    assert len(extracted["certifications"]) >= 3


def test_end_to_end_scoring_fresher_software_engineer():
    from app.services.scoring import ComponentScoringService, WeightCalculationService, RecommendationService

    class DummySoftwareEngineerJD:
        required_skills = [
            "Java", "Python", "C++", "JavaScript", "Object-Oriented Programming",
            "Data Structures and Algorithms", "HTML", "CSS", "REST API", "JSON",
            "SQL", "MySQL", "PostgreSQL", "Git", "GitHub", "Software Testing", "Debugging"
        ]
        preferred_skills = [
            "React", "Angular", "Spring Boot", "FastAPI", "Node.js", "Docker", "Postman", "CI/CD"
        ]
        skills = required_skills + preferred_skills
        degree_requirements = ["Bachelor of Technology"]
        experience_requirements = [{"minimum_months": 0, "display_value": "0-1 year"}]
        keywords = required_skills + preferred_skills
        domain = "Software Engineering"

    class DummyArunResume:
        skills = [
            "Python", "FastAPI", "PostgreSQL", "React", "Docker", "Java", "JavaScript",
            "Git", "Node.js", "C++", "SQL", "HTML", "CSS", "CI/CD", "Spring Boot",
            "MySQL", "Postman", "Agile", "SDLC", "Software Testing", "Debugging",
            "Object-Oriented Programming", "Data Structures and Algorithms", "REST API",
            "JSON", "GitHub", "API Testing"
        ]
        education = [{
            "degree": "Bachelor of Technology",
            "institution": "SRM Institute of Science and Technology",
            "field_of_study": "Computer Science and Engineering"
        }]
        experience = [{
            "company": "Technology Solutions Pvt. Ltd.",
            "title": "Software Engineering Intern",
            "duration_months": 3
        }]
        projects = [
            {"name": "AI Resume Screener", "description": "Python FastAPI PostgreSQL REST API", "technologies": ["Python", "FastAPI", "PostgreSQL", "REST API"]},
            {"name": "Task Management Web Application", "description": "React SQL Postman REST API", "technologies": ["React", "SQL", "Postman", "REST API"]},
            {"name": "Student Performance Analytics", "description": "Python SQL Pandas", "technologies": ["Python", "SQL", "Pandas"]}
        ]
        certifications = ["Python Programming", "SQL and Database Fundamentals", "Git and GitHub Fundamentals"]
        languages = ["English"]

    components = ComponentScoringService().score(DummyArunResume(), DummySoftwareEngineerJD(), config=None)

    assert components.skills.score == 100.0
    assert len(components.skills.missing_items) == 0
    assert components.education.score == 100.0
    assert components.experience.score == 100.0

    final_score = WeightCalculationService.final_score(
        weighted_total=100.0, penalty_total=0.0, bonus_total=0.0, components=components
    )
    assert final_score >= 85.0, f"Expected shortlist score >= 85.0, got {final_score}"

    recommendation = RecommendationService.recommend(final_score, passing_score=70.0, knocked_out=False)
    assert recommendation == "SHORTLIST"


def test_requirement_builder_empty_required_skills_no_mandatory_promotion():
    from app.services.matching_service import RequirementBuilder

    class DummyJobEmptyReq:
        required_skills = []
        preferred_skills = ["React"]
        skills = ["Python", "SQL", "React"]

    reqs = RequirementBuilder.build(DummyJobEmptyReq())
    mandatory_reqs = [r for r in reqs if r.required]
    assert len(mandatory_reqs) == 0







