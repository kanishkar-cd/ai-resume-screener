import pytest
from app.services.affinda_mapper import map_affinda_resume
from app.services.extractors.resume_extractor import ResumeExtractor


def test_affinda_mapper_fallback_merging():
    """Verify that empty/null fields in raw Affinda responses are populated using local fallback extraction."""
    raw_affinda = {
        "candidateName": None,
        "email": [],
        "phoneNumber": [],
        "location": {},
        "jobTitles": [],
        "skill": [],
        "education": [],
        "workExperience": [],
        "certification": [],
        "project": [
            {
                "projectTitle": "Cloud Infrastructure Monitoring & Automation",
                "projectDescription": "Centralized AWS/Linux monitoring with CloudWatch, Prometheus and Grafana.",
                "technologies": "AWS, Linux, CloudWatch, Prometheus, Grafana",
            }
        ],
    }

    raw_text = """ARJUN KUMAR SysOps Engineer | Infrastructure & Cloud Operations
Chennai, India | arjun.kumar@email.com | +91 -9876543210

PROFESSIONAL SUMMARY
SysOps Engineer with 3 years of experience supporting Linux/Windows infrastructure, cloud environments, monitoring, troubleshooting, automation and IT operations.

TECHNICAL / CORE SKILLS
Linux • Windows Server • AWS EC2/S3/IAM • Azure • Active Directory • DNS • DHCP • TCP/IP • VPN • Firewalls • Grafana • Prometheus • CloudWatch • Nagios • Python • PowerShell • Bash

PROFESSIONAL EXPERIENCE
• Managed Linux and Windows production servers.
• Monitored infrastructure using CloudWatch, Grafana and Nagios.

PROJECT
• Cloud Infrastructure Monitoring & Automation • centralized AWS/Linux monitoring with CloudWatch, Prometheus and Grafana.

CERTIFICATIONS
AWS Certified Cloud Practitioner • Microsoft Azure Fundamentals • ITIL Foundation

EDUCATION
Bachelor of Engineering • Computer Science, XYZ Engineering College
"""

    extracted, normalized = map_affinda_resume(raw_affinda, provider_id="test_doc_123", source_text=raw_text)

    # 1. Candidate Name
    assert extracted["candidate_name"] == "Arjun Kumar"

    # 2. Email & Phone
    assert extracted["email"] == "arjun.kumar@email.com"
    assert extracted["phone"] is not None

    # 3. Location
    assert extracted["location"] == "Chennai, Tamil Nadu, India"

    # 4. Skills
    assert "Linux" in extracted["skills"]
    assert "Python" in extracted["skills"]
    assert len(extracted["skills"]) >= 5

    # 5. Projects & Technologies
    assert len(extracted["projects"]) >= 1
    p0 = extracted["projects"][0]
    assert p0["name"] == "Cloud Infrastructure Monitoring & Automation"
    assert "AWS" in p0["technologies"]
    assert "Linux" in p0["technologies"]

    # 6. Normalized Profile
    assert normalized["email"] == "arjun.kumar@email.com"
    assert "Linux" in normalized["skills"]
