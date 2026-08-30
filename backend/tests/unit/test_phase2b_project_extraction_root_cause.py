import pytest
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.affinda_mapper import map_affinda_resume, _normalize_technology_entries


def test_sri_geethani_three_projects_extracted_cleanly():
    source_text = (
        "SRI GEETHANI R\n"
        "EDUCATION\n"
        "Sri Eshwar College of Engineering B.Tech(CSBS) CGPA: 8.4\n"
        "INTERNSHIP\n"
        "PQA INTERN-Nimble Wireless, Privated Ltd Analyzed and validated 11,000+ test cases.\n"
        "PROJECTS\n"
        "SECURE VOTING SYSTEM 2025 Developed a secure full-stack digital voting platform with voter authentication, "
        "vote casting, and real-time election result monitoring. Implemented secure login and MongoDB-based voter validation. "
        "Tools Used: React.js, Node.js, Express.js, MongoDB, REST APIs\n"
        "SMART TROLLEYS . 2025 Developed a smart supermarket web application using React.js to enhance customer shopping.\n"
        "2024 FASHIONBOOK-(FRONTEND) Developed a responsive fashion-sharing web application using Next.js with dynamic routing. "
        "Tools Used: Next.js\n"
        "SKILLS\n"
        "C++, HTML, CSS, JavaScript, React.js, Node.js"
    )

    mapped, _ = map_affinda_resume({}, source_text=source_text)
    projs = mapped.get("projects", [])
    assert len(projs) == 3

    names = [p["name"] for p in projs]
    assert "SECURE VOTING SYSTEM" in names[0]
    assert "SMART TROLLEYS" in names[1]
    assert "FASHIONBOOK" in names[2]

    # Check project-specific technologies
    assert "MongoDB" in projs[0]["technologies"]
    assert "React" in projs[1]["technologies"]
    assert "Next.js" in projs[2]["technologies"]
    assert "Next.js" not in projs[0]["technologies"]


def test_priya_sharma_embedded_experience_project_extracted():
    source_text = (
        "PRIYA SHARMA Security Operations Engineer | SOC Analyst\n"
        "PROFESSIONAL EXPERIENCE\n"
        "• Monitored security alerts using Splunk and Microsoft Sentinel.\n"
        "• Investigated suspicious login activity and endpoint alerts.\n"
        "• Automated SOC activities using Python and PowerShell.\n"
        "PROJECT • SIEM-Based Threat Detection & Incident Response • centralized monitoring with Splunk and Microsoft Sentinel. "
        "• Integrated Windows/Linux logs, created authentication detections and KQL queries. "
        "• Mapped detections to MITRE ATT&CK and automated investigation tasks with Python.\n"
        "TECHNICAL / CORE SKILLS\n"
        "SOC, Splunk, Microsoft Sentinel, KQL, Python, PowerShell"
    )

    mapped, _ = map_affinda_resume({}, source_text=source_text)
    projs = mapped.get("projects", [])
    assert len(projs) == 1
    assert projs[0]["name"] == "SIEM-Based Threat Detection & Incident Response"
    assert "centralized monitoring with Splunk" in projs[0]["description"]
    
    # Verify all project technologies mentioned in description are extracted
    techs = projs[0]["technologies"]
    assert "Splunk" in techs
    assert "Microsoft Sentinel" in techs
    assert "KQL" in techs
    assert "MITRE ATT&CK" in techs
    assert "Python" in techs
    assert "Linux" in techs


def test_arjun_cloud_monitoring_technologies_extracted():
    source_text = (
        "ARJUN VERMA DevOps & Cloud Engineer\n"
        "PROJECTS\n"
        "Project: Cloud Infrastructure Monitoring & Automation\n"
        "• Deployed real-time cluster monitoring with AWS, Linux, CloudWatch, Prometheus, Grafana, Python and PowerShell.\n"
        "• Built automated alert notification bot integrated with Slack.\n"
    )

    mapped, _ = map_affinda_resume({}, source_text=source_text)
    projs = mapped.get("projects", [])
    assert len(projs) == 1
    assert projs[0]["name"] == "Cloud Infrastructure Monitoring & Automation"
    
    techs = projs[0]["technologies"]
    assert "AWS" in techs
    assert "Linux" in techs
    assert "CloudWatch" in techs
    assert "Prometheus" in techs
    assert "Grafana" in techs
    assert "Python" in techs
    assert "PowerShell" in techs


def test_rahul_menon_no_invented_technologies():
    source_text = (
        "RAHUL MENON PMO Analyst | Project Coordinator\n"
        "PROFESSIONAL EXPERIENCE\n"
        "• Coordinated project activities across engineering and IT teams.\n"
        "• Maintained RAID logs for risks, assumptions, issues and dependencies.\n"
        "PROJECT • Enterprise IT Transformation Program • supported PMO activities for a multi-team infrastructure transformation. "
        "• Maintained plans/milestones, tracked dependencies across infrastructure, security and application teams. "
        "• Maintained RAID logs, prepared executive dashboards and tracked risks/issues.\n"
        "TECHNICAL / CORE SKILLS\n"
        "Project Planning, Jira, Confluence, MS Project, Power BI"
    )

    mapped, _ = map_affinda_resume({}, source_text=source_text)
    projs = mapped.get("projects", [])
    assert len(projs) == 1
    assert projs[0]["name"] == "Enterprise IT Transformation Program"
    assert projs[0]["technologies"] == []



def test_rahul_menon_embedded_experience_project_extracted():
    source_text = (
        "RAHUL MENON PMO Analyst | Project Coordinator\n"
        "PROFESSIONAL EXPERIENCE\n"
        "• Coordinated project activities across engineering and IT teams.\n"
        "• Maintained RAID logs for risks, assumptions, issues and dependencies.\n"
        "• Prepared management dashboards using Excel and Power BI.\n"
        "PROJECT • Enterprise IT Transformation Program • supported PMO activities for a multi-team infrastructure transformation. "
        "• Maintained plans/milestones, tracked dependencies across infrastructure, security and application teams. "
        "• Maintained RAID logs, prepared executive dashboards and tracked risks/issues.\n"
        "TECHNICAL / CORE SKILLS\n"
        "Project Planning, Jira, Confluence, MS Project, Power BI"
    )

    mapped, _ = map_affinda_resume({}, source_text=source_text)
    projs = mapped.get("projects", [])
    assert len(projs) == 1
    assert projs[0]["name"] == "Enterprise IT Transformation Program"
    assert "multi-team infrastructure transformation" in projs[0]["description"]


def test_internship_and_education_not_contaminated_into_projects():
    source_text = (
        "EDUCATION\n"
        "Stanford University - B.S. Computer Science\n"
        "WORK EXPERIENCE\n"
        "Software Engineer Intern at Google - Worked on search indexing optimizations.\n"
        "PROJECTS\n"
        "Project: Microservice Engine\n"
        "• Built distributed message queue using Rust and gRPC.\n"
        "CERTIFICATIONS\n"
        "AWS Certified Solutions Architect"
    )

    mapped, _ = map_affinda_resume({}, source_text=source_text)
    projs = mapped.get("projects", [])
    assert len(projs) == 1
    assert projs[0]["name"] == "Microservice Engine"
    assert "Stanford" not in projs[0]["description"]
    assert "Google" not in projs[0]["description"]
    assert "AWS Certified Solutions Architect" not in projs[0]["description"]


def test_no_duplicate_projects_generated():
    source_text = (
        "PROJECTS\n"
        "Project: Payment Gateway | Stripe, FastAPI\n"
        "• Handled webhook events and payment intents.\n"
        "Project: Payment Gateway | Stripe, FastAPI\n"
        "• Handled webhook events and payment intents.\n"
    )
    mapped, _ = map_affinda_resume({}, source_text=source_text)
    projs = mapped.get("projects", [])
    # Duplicate projects with identical name should be deduplicated
    names = [p["name"] for p in projs]
    assert len(set(names)) == len(names)


def test_no_technology_only_fake_projects():
    # Verify that a skill list or tech keywords do not create projects
    source_text = (
        "SKILLS\n"
        "Python, React, Docker, Kubernetes, AWS, PostgreSQL, MongoDB, Redis\n"
        "EDUCATION\n"
        "MIT - Computer Science\n"
    )
    mapped, _ = map_affinda_resume({}, source_text=source_text)
    projs = mapped.get("projects", [])
    assert len(projs) == 0


def test_technology_character_splitting_never_occurs():
    techs = _normalize_technology_entries("React.js, Node.js, Express.js, MongoDB, REST APIs")
    assert techs == ["React.js", "Node.js", "Express.js", "MongoDB", "REST APIs"]
    assert "R" not in techs
    assert "e" not in techs
