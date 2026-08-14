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
