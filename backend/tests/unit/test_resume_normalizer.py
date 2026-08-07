from types import SimpleNamespace

from app.services.normalizers.resume_normalizer import ResumeNormalizer


def test_complete_resume_normalization() -> None:
    extracted = SimpleNamespace(
        skills=["python", "PYTHON", "postgres"],
        education=[{"degree": "B.E.", "field_of_study": "Computer Science", "institution": "Example University", "year": "2020"}],
        companies=["Acme Corp."], designation="C++ Developer",
        experience=[{"company": "Acme Corp.", "title": "Sr. Backend Dev", "duration": "2021 - Present", "responsibilities": []}],
        phone="+91-98765-43210", email="JANE.DOE@EXAMPLE.COM ", location="Bangalore",
        languages=["Eng", "Hindi"], certifications=["PMP"],
    )
    result = ResumeNormalizer().normalize(extracted)
    assert result["skills"] == ["Python", "PostgreSQL"]
    assert result["education"][0]["degree"] == "Bachelor of Engineering"
    assert result["companies"] == ["Acme Corporation"]
    assert result["job_titles"] == ["Software Engineer", "Senior Backend Engineer"]
    assert result["experience"][0]["is_current"] is True
    assert result["phone"] == "+919876543210"
    assert result["email"] == "jane.doe@example.com"
    assert result["locations"][0]["country_code"] == "IN"
    assert result["languages"] == ["English", "Hindi"]
    assert result["certifications"] == ["Project Management Professional (PMP)"]
    assert result["ruleset_version"] == "1.0.0"


def test_alias_resolution_and_deduplication() -> None:
    extracted = SimpleNamespace(
        skills=["python", "PYTHON", "Py", "reactjs", "React"],
        education=[], companies=[], designation=None, experience=[],
        phone=None, email=None, location=None, languages=[], certifications=[],
    )
    result = ResumeNormalizer().normalize(extracted)
    assert result["skills"] == ["Python", "React"]


def test_date_and_experience_normalization() -> None:
    extracted = SimpleNamespace(
        skills=[], education=[], companies=[], designation=None,
        experience=[
            {
                "company": "Customer Centria",
                "designation": "Database Management Intern",
                "start_date": "08/2025",
                "end_date": "10/2025",
                "duration": "Three Months",
            }
        ],
        phone=None, email=None, location=None, languages=[], certifications=[],
    )
    result = ResumeNormalizer().normalize(extracted)
    exp = result["experience"][0]
    assert exp["start_date"] == "2025-08"
    assert exp["end_date"] == "2025-10"
    assert exp["is_current"] is False
    assert exp["duration_months"] == 3


def test_phone_email_and_certification_normalization() -> None:
    extracted = SimpleNamespace(
        skills=[], education=[], companies=[], designation=None, experience=[],
        phone=" +91 9043652396 ", email=" Sasikumar80989705@GMAIL.com ", location="Coimbatore",
        languages=[], certifications=["AWS Certified Cloud Practitioner", "PMP"],
    )
    result = ResumeNormalizer().normalize(extracted)
    assert result["phone"] == "+919043652396"
    assert result["email"] == "sasikumar80989705@gmail.com"
    assert "AWS Certified Cloud Practitioner" in result["certifications"]
    assert "Project Management Professional (PMP)" in result["certifications"]
    assert result["normalization_metadata"]["field_confidence"]["email"] == 1.0


def test_stage4_final_polish_validation() -> None:
    extracted = SimpleNamespace(
        candidate_name=" Shri Harini Karthika ",
        skills=["python", "PYTHON", "AWS", "Docker"],
        education=[],
        companies=["Customer Centria", "Customer Centria"],
        designation="Database Management Intern",
        experience=[],
        phone=" +91-9043652396 ",
        email=" sasikumar80989705@gmail.com ",
        location="Coimbatore, Tamil Nadu, India",
        languages=[],
        certifications=["MongoDB", "Azure DP-900"],
    )
    result = ResumeNormalizer().normalize(extracted)

    # 1. Location parsing
    loc = result["locations"][0]
    assert loc["city"] == "Coimbatore"
    assert loc["region"] == "Tamil Nadu"
    assert loc["country"] == "India"
    assert loc["country_code"] == "IN"
    assert loc["display_name"] == "Coimbatore, Tamil Nadu, India"

    # 2. Confidence 1.0 for deterministic fields
    meta = result["normalization_metadata"]
    conf = meta["field_confidence"]
    assert conf["email"] == 1.0
    assert conf["phone"] == 1.0
    assert conf["skills"] == 1.0
    assert conf["locations"] == 1.0
    assert conf["companies"] == 1.0

    # 3. Metadata extensions & warning suppression
    assert meta["aliases_resolved"] >= 1
    assert meta["duplicates_removed"] >= 1
    assert "skills" in meta["fields_normalized"]
    assert "locations" in meta["fields_normalized"]

    # Warnings must not contain preserved valid standard fields
    for warn in meta["warnings"]:
        assert "companies" not in warn
        assert "certifications" not in warn
        assert "locations" not in warn
        assert "phone" not in warn


def test_stage4_acceptance_criteria() -> None:
    """Explicit acceptance test for Indian E.164 phone, company confidence = 1.0, and country_code = IN."""
    extracted = SimpleNamespace(
        candidate_name="Shri Harini Karthika",
        skills=["Python"], education=[],
        companies=["Customer Centria"], designation="Database Management Intern",
        experience=[], phone="9043652396", email="sasikumar80989705@gmail.com",
        location="Coimbatore, Tamil Nadu, India", languages=[], certifications=[],
    )
    result = ResumeNormalizer().normalize(extracted)

    # Acceptance 1: Phone = +919043652396
    assert result["phone"] == "+919043652396"

    # Acceptance 2: Company confidence = 1.0
    meta = result["normalization_metadata"]
    assert meta["field_confidence"]["companies"] == 1.0

    # Acceptance 3: Country code = IN
    assert result["locations"][0]["country_code"] == "IN"

