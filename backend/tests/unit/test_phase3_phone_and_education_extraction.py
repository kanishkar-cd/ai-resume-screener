import pytest
from app.services.extractors.resume_extractor import ResumeExtractor
from app.services.affinda_mapper import map_affinda_resume
from app.services.normalizers.resume_normalizer import ResumeNormalizer
from app.models.extracted_info import ExtractedResumeModel


# ==============================================================================
# PHASE 3A — PHONE EXTRACTION TESTS
# ==============================================================================

def test_phone_extraction_indian_with_country_code():
    text = (
        "ASWIN SURIYA C\n"
        "aswinsuriya16@gmail.com | +91 9344081155 | Coimbatore, India\n"
        "EDUCATION\n"
        "B.E. Computer Science and Engineering"
    )
    mapped, normalized = map_affinda_resume({}, source_text=text)
    assert mapped["phone"] == "+91 9344081155"
    assert normalized["phone"] == "+919344081155"


def test_phone_extraction_indian_without_spaces_or_prefix():
    text = (
        "JAISHREE Y\n"
        "+919361280237 | jaishree@email.com | GitHub | LinkedIn\n"
        "EDUCATION\n"
        "B.E. Computer and Communication Engineering"
    )
    mapped, normalized = map_affinda_resume({}, source_text=text)
    assert mapped["phone"] == "+919361280237"
    assert normalized["phone"] == "+919361280237"


def test_phone_extraction_labeled_phone():
    text = (
        "SRI GEETHANI R Phone : 7397454084 srigeethani@email.com\n"
        "EDUCATION\n"
        "Sri Eshwar College of Engineering B.Tech(CSBS)"
    )
    mapped, normalized = map_affinda_resume({}, source_text=text)
    assert mapped["phone"] == "7397454084"
    assert normalized["phone"] == "+917397454084"


def test_phone_extraction_masked_number_returns_none():
    text = (
        "VARSHINI Senior Data Analyst\n"
        "Chennai, India | +91-XXXXXXXXXX | varshini@email.com\n"
        "SUMMARY\n"
        "Senior Data Analyst with 6+ years of experience."
    )
    mapped, normalized = map_affinda_resume({}, source_text=text)
    assert mapped["phone"] is None
    assert normalized["phone"] is None


def test_phone_extraction_no_phone_present_returns_none():
    text = (
        "ARJUN VERMA DevOps Engineer\n"
        "arjun.verma@email.com | Bangalore, India\n"
        "PROJECTS\n"
        "Cloud Infrastructure Automation"
    )
    mapped, normalized = map_affinda_resume({}, source_text=text)
    assert mapped["phone"] is None
    assert normalized["phone"] is None


def test_phone_extraction_never_matches_pin_codes_or_dates():
    text = (
        "KANDIDATE NAME\n"
        "kandidate@email.com\n"
        "Coimbatore - 641032, Tamil Nadu\n"
        "EDUCATION\n"
        "2023 - 2027\n"
        "Roll No: 23102050"
    )
    mapped, normalized = map_affinda_resume({}, source_text=text)
    assert mapped["phone"] is None
    assert normalized["phone"] is None


# ==============================================================================
# PHASE 3B — EDUCATION EXTRACTION TESTS
# ==============================================================================

def test_education_three_tier_college_hsc_sslc_sri_geethani():
    source_text = (
        "SRI GEETHANI R\n"
        "EDUCATION\n"
        "Sri Eshwar College of Engineering MVM Higher Secondary School B.Tech(CSBS) CGPA: 8.4 MVM Higher Secondary School HSC SSLC 94.06% PASS | GitHub LinkedIn 2023-2027 2019-2021 2018-2019\n"
        "PROJECTS\n"
        "SECURE VOTING SYSTEM 2025 Developed a secure full-stack digital voting platform."
    )
    mapped, _ = map_affinda_resume({}, source_text=source_text)
    edu = mapped.get("education", [])
    assert len(edu) == 3

    # Entry 1: College Degree
    assert edu[0]["degree"] == "Bachelor of Technology"
    assert "Sri Eshwar College" in (edu[0]["institution"] or "")
    assert edu[0]["field_of_study"] == "Computer Science and Business Systems"
    assert "8.4" in (edu[0].get("grade") or "")
    assert "2027" in (edu[0].get("year") or "")

    # Entry 2: Higher Secondary (12th)
    assert edu[1]["degree"] == "Higher Secondary (12th)"
    assert "MVM" in (edu[1]["institution"] or "")
    assert edu[1]["field_of_study"] is None
    assert "94.06" in (edu[1].get("grade") or "")

    # Entry 3: Secondary School (10th)
    assert edu[2]["degree"] == "Secondary School (10th)"
    assert "MVM" in (edu[2]["institution"] or "")
    assert edu[2]["field_of_study"] is None


def test_education_three_tier_college_hsc_sslc_jaishree():
    source_text = (
        "JAISHREE Y\n"
        "EDUCATION\n"
        "B.E.CCE Sri Eshwar College of Engineering | CGPA : 8.16 (Upto 5th Semester) 2023 - 2027 HSC Model School Veerapandi | 92% 2022 - 2023 SSLC GGHSS | 2020 - 2021\n"
        "SKILLS\n"
        "Python, Flask, Selenium"
    )
    mapped, _ = map_affinda_resume({}, source_text=source_text)
    edu = mapped.get("education", [])
    assert len(edu) == 3

    assert edu[0]["degree"] == "Bachelor of Engineering"
    assert "Sri Eshwar College" in (edu[0]["institution"] or "")
    assert edu[0]["field_of_study"] == "Computer and Communication Engineering"
    assert "8.16" in (edu[0].get("grade") or "")

    assert edu[1]["degree"] == "Higher Secondary (12th)"
    assert "Model School" in (edu[1]["institution"] or "")
    assert "92%" in (edu[1].get("grade") or "")

    assert edu[2]["degree"] == "Secondary School (10th)"
    assert "GGHSS" in (edu[2]["institution"] or "")


def test_education_multiline_college_plus_hsc_muthu():
    source_text = (
        "MUTHU VISALAKSHI\n"
        "EDUCATION\n"
        "Sri Eshwar College of Engineering, Coimbatore\n"
        "2023 - 2027\n"
        "Bachelor of Technology: Artificial Intelligence and Data Science\n"
        "CGPA: 8.23\n"
        "BVM Matric Higher Secondary School\n"
        "2021 - 2023\n"
        "Higher Secondary Education (State Board) - Percentage: 85.3%\n"
        "EXPERIENCE\n"
        "Cloud Destinations"
    )
    mapped, _ = map_affinda_resume({}, source_text=source_text)
    edu = mapped.get("education", [])
    assert len(edu) == 2

    assert edu[0]["degree"] == "Bachelor of Technology"
    assert "Sri Eshwar College" in (edu[0]["institution"] or "")
    assert edu[0]["field_of_study"] == "Artificial Intelligence and Data Science"
    assert "8.23" in (edu[0].get("grade") or "")

    assert edu[1]["degree"] == "Higher Secondary (12th)"
    assert "BVM" in (edu[1]["institution"] or "")
    assert "85.3" in (edu[1].get("grade") or "")


def test_education_multiple_university_degrees():
    source_text = (
        "ALEXANDER WANG\n"
        "EDUCATION\n"
        "Stanford University | 2021 - 2023\n"
        "Master of Science in Computer Science | GPA: 3.9\n"
        "University of California, Berkeley | 2017 - 2021\n"
        "Bachelor of Science in Electrical Engineering & Computer Science | GPA: 3.8\n"
        "SKILLS\n"
        "Distributed Systems, Go, Kubernetes"
    )
    mapped, _ = map_affinda_resume({}, source_text=source_text)
    edu = mapped.get("education", [])
    assert len(edu) == 2

    assert edu[0]["degree"] == "Master of Science"
    assert "Stanford" in (edu[0]["institution"] or "")
    assert "Computer Science" in (edu[0]["field_of_study"] or "")

    assert edu[1]["degree"] == "Bachelor of Science"
    assert "Berkeley" in (edu[1]["institution"] or "")


def test_education_single_degree_aswin():
    source_text = (
        "ASWIN SURIYA C\n"
        "EDUCATION\n"
        "B.E. Computer Science and Engineering\n"
        "Sri Eshwar College of Engineering, Coimbatore\n"
        "CGPA: 8.12\n"
        "2021 - 2025\n"
        "EXPERIENCE\n"
        "Software Engineer at Cloud Destinations"
    )
    mapped, _ = map_affinda_resume({}, source_text=source_text)
    edu = mapped.get("education", [])
    assert len(edu) == 1
    assert edu[0]["degree"] == "Bachelor of Engineering"
    assert "Sri Eshwar College" in (edu[0]["institution"] or "")
    assert edu[0]["field_of_study"] == "Computer Science and Engineering"
    assert "8.12" in (edu[0].get("grade") or "")


def test_normalization_education_canonicalization():
    normalizer = ResumeNormalizer()
    extracted = ExtractedResumeModel(
        candidate_name="Test Candidate",
        email="test@email.com",
        phone="+91 9344081155",
        location="Coimbatore, India",
        skills=["Python"],
        education=[
            {"degree": "B.E.", "institution": "Sri Eshwar College of Engineering", "field_of_study": "CSE", "year": "2021 - 2025"},
            {"degree": "HSC", "institution": "Model Higher Secondary School", "field_of_study": None, "year": "2019 - 2021"},
            {"degree": "SSLC", "institution": "Model High School", "field_of_study": None, "year": "2018 - 2019"}
        ],
        experience=[],
        projects=[],
        certifications=[],
        languages=[]
    )
    normalized = normalizer.normalize(extracted)
    assert normalized["phone"] == "+919344081155"
    edu_norm = normalized["education"]
    assert len(edu_norm) == 3
    assert edu_norm[0]["degree"] == "Bachelor of Engineering"
    assert edu_norm[0]["graduation_date"] == "2025"
    assert edu_norm[1]["degree"] == "Higher Secondary (12th)"
    assert edu_norm[1]["graduation_date"] == "2021"
    assert edu_norm[2]["degree"] == "Secondary School (10th)"
    assert edu_norm[2]["graduation_date"] == "2019"
