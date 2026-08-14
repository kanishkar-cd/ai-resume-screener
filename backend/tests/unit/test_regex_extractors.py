from app.services.extractors.job_extractor import JobDescriptionExtractor
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.pipeline.extraction_pipeline import EMAIL_PATTERN, PHONE_PATTERN, URL_PATTERN


def test_contact_patterns_extract_supported_formats() -> None:
    text = "Jane Doe jane.doe+dev@sub.example.com +91-9876543210 https://example.com/profile"
    assert EMAIL_PATTERN.search(text).group(0) == "jane.doe+dev@sub.example.com"
    assert PHONE_PATTERN.search(text).group(0) == "+91-9876543210"
    assert URL_PATTERN.search(text).group(0) == "https://example.com/profile"


def test_resume_extraction_returns_structured_fields_and_confidence() -> None:
    result = ResumeExtractor().extract("""Jane Doe
Senior Backend Engineer
Email: jane.doe+test@gmail.com
Phone: +91 98765 43210
Location: Bengaluru, India

PROFESSIONAL SUMMARY
Experienced Senior Software Engineer with expertise in Python, FastAPI, MongoDB, Jenkins and Terraform.

TECHNICAL SKILLS
Python, FastAPI, PostgreSQL, Docker, HTML, CSS, MongoDB, Jenkins, Terraform, DynamoDB, Redis, GraphQL, REST API, Linux, CI/CD, GCP, Go

EDUCATION
Bachelor of Technology in Computer Science, Example Institute of Technology, 2020 | CGPA: 8.5/10

PROFESSIONAL EXPERIENCE
Senior Backend Engineer at Acme Technologies | Jan 2021 - Present
- Architected microservices with FastAPI and MongoDB.
- Deployed CI/CD pipelines using Jenkins and Terraform.

KEY PROJECTS
E-Commerce Microservices:
- Developed scalable order processing service in Go and REST API.
- Implemented caching with Redis and events with Kafka.

CERTIFICATIONS & LICENSES
AWS Certified Solutions Architect (2022)

INTERNSHIP EXPERIENCE
Software Engineer Intern at Beta Labs | May 2019 - Aug 2019
- Worked on HTML and CSS frontend bugs.

LANGUAGES
English, Hindi
""")

    assert result["candidate_name"] == "Jane Doe"
    assert result["email"] == "jane.doe+test@gmail.com"
    assert result["phone"] == "+91 98765 43210"
    assert "Bengaluru" in result["location"]
    assert "HTML" in result["skills"]
    assert "MongoDB" in result["skills"]
    assert "Jenkins" in result["skills"]
    assert "Terraform" in result["skills"]
    assert "DynamoDB" in result["skills"]

    # Education
    assert len(result["education"]) >= 1
    assert result["education"][0]["degree"] == "Bachelor of Technology"
    assert "8.5/10" in (result["education"][0]["grade"] or "")

    # Experience
    assert len(result["experience"]) >= 1
    assert result["experience"][0]["company"] == "Acme Technologies"
    assert result["experience"][0]["title"] == "Senior Backend Engineer"

    # Projects
    assert len(result["projects"]) == 1
    assert result["projects"][0]["name"] == "E-Commerce Microservices"
    assert "Redis" in result["projects"][0]["technologies"]

    # Certifications boundary leakage test
    assert len(result["certifications"]) == 1
    assert "AWS Certified Solutions Architect" in result["certifications"][0]
    assert not any("Intern" in c for c in result["certifications"])

    # Metadata quality
    assert result["raw_metadata"]["section_detection_score"] >= 0.8
    assert result["raw_metadata"]["overall_quality_score"] >= 0.8


def test_job_description_extraction_returns_requirements() -> None:
    result = JobDescriptionExtractor().extract("""Backend Software Engineer
RESPONSIBILITIES
- Build FastAPI services
REQUIREMENTS
Python, PostgreSQL, Docker and 5+ years of experience
EDUCATION
Bachelor of Science required
""")
    assert result["domain"] == "Software Engineering"
    assert "Python" in result["skills"]
    assert result["experience"] == ["5+ years of experience"]
    assert result["responsibilities"] == ["Build FastAPI services"]


def test_ocr_resume_projects_extraction_without_prefix() -> None:
    raw_ocr_resume = """HARSHINI R
Software Engineer

TECHNICAL SKILLS
Python, JavaScript, React, Node.js, HTML, CSS, C++

PROJECT EXPERIENCE
Software Development Training Website
Developed a full-stack interactive website using HTML, CSS, JavaScript, and React.
Implemented responsive user interfaces and modular backend components.

PLC based Smart Parking System with IoT
Engineered an automated parking management system using PLC controllers and IoT sensors.
Integrated real-time slot tracking and monitoring.

Frontend E-commerce Platform
Built a modern online shopping UI with React, Redux, and Tailwind.
Optimized state management and page rendering speed.
"""
    result = ResumeExtractor().extract(raw_ocr_resume)
    projects = result["projects"]
    assert len(projects) == 3

    assert projects[0]["name"] == "Software Development Training Website"
    assert "React" in projects[0]["technologies"]
    assert "Software Development Training Website" in projects[0]["description"]
    assert "PLC" not in projects[0]["description"]

    assert projects[1]["name"] == "PLC based Smart Parking System with IoT"
    assert "PLC based Smart Parking System with IoT" in projects[1]["description"]
    assert "E-commerce" not in projects[1]["description"]

    assert projects[2]["name"] == "Frontend E-commerce Platform"
    assert "React" in projects[2]["technologies"]
    assert "Frontend E-commerce Platform" in projects[2]["description"]


def test_uploaded_jd_extraction() -> None:
    jd_text = """Software Engineer

JOB RESPONSIBILITIES
Design, develop, and test software components for embedded and web applications.
Collaborate with cross-functional teams to integrate software with hardware systems.
Maintain code quality, documentation, and perform system troubleshooting.

BASIC QUALIFICATIONS
Bachelor of Engineering in Computer Science, Electrical, or related field.
Proficiency in C++, JavaScript, HTML, CSS, and SQL.
Understanding of software development life cycle.

PREFERRED QUALIFICATIONS / KEYWORDS
Experience with IoT, PLC, PLC Programming, and Embedded Systems.
Strong problem-solving and debugging skills.
"""
    result = JobDescriptionExtractor().extract(jd_text)

    # Job title / domain
    assert result["domain"] == "Software Engineering"

    # Skills extraction
    expected_skills = {"SQL", "HTML", "JavaScript", "C++", "CSS", "Embedded Systems", "PLC Programming", "PLC", "IoT"}
    extracted_skills_set = set(result["skills"])
    assert expected_skills.issubset(extracted_skills_set), f"Missing skills. Got: {extracted_skills_set}"

    # Education extraction (returns clean degree string)
    assert result["education"] == ["Bachelor of Engineering"]

    # Responsibilities extraction (full responsibilities paragraph lines)
    assert len(result["responsibilities"]) == 3
    assert "Design, develop, and test software components" in result["responsibilities"][0]
    assert "Collaborate with cross-functional teams" in result["responsibilities"][1]
    assert "Maintain code quality" in result["responsibilities"][2]

    # Preferred / Keywords
    keyword_set = set(result["keywords"])
    for kw in ("IoT", "PLC", "Embedded Systems", "JavaScript", "HTML", "CSS", "C++", "SQL", "Software Engineer"):
        assert kw in keyword_set, f"Missing keyword {kw}. Got: {keyword_set}"


def test_doc_248ef7dc_jd_prose_responsibility() -> None:
    jd_text = """Software Engineer

RESPONSIBILITIES
Responsibilities include developing software applications, working with embedded systems, building web interfaces, and contributing to IoT-based projects.

BASIC QUALIFICATIONS
Bachelor of Engineering in Computer Science, Electrical, or related field.
Proficiency in C++, JavaScript, HTML, CSS, and SQL.
"""
    result = JobDescriptionExtractor().extract(jd_text)
    assert result["domain"] == "Software Engineering"
    assert result["education"] == ["Bachelor of Engineering"]
    assert len(result["responsibilities"]) == 1
    expected_resp = "Responsibilities include developing software applications, working with embedded systems, building web interfaces, and contributing to IoT-based projects."
    assert result["responsibilities"][0] == expected_resp




