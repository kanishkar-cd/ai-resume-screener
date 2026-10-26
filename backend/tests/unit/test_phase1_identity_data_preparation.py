"""Unit tests for Phase 1: Candidate Identity Data Preparation.

Covers:
1. Email normalization (trimming whitespace, lowercasing, format validation).
2. Phone normalization via `phonenumbers` (country-code preservation, E.164 formatting).
3. Candidate name normalization (casing, initials preservation, punctuation cleaning).
4. Preservation of original values alongside normalized values.
5. Handling of missing, invalid, or ambiguous identity fields.
6. ResumeNormalizer end-to-end identity preparation.
7. Zoho Recruit candidate identity data handling.
"""

from types import SimpleNamespace
from typing import Any
import pytest

from app.services.pipeline.identity_rules import (
    normalize_candidate_identity,
    normalize_candidate_name,
    normalize_email_address,
    normalize_phone_number,
)
from app.services.pipeline.normalization_rules import (
    NormalizationAudit,
    normalize_email,
    normalize_name,
    normalize_phone,
)
from app.services.normalizers.resume_normalizer import ResumeNormalizer


# ==============================================================================
# 1. Email Normalization Tests
# ==============================================================================


@pytest.mark.parametrize(
    "raw_input, expected_canonical",
    [
        ("user@example.com", "user@example.com"),
        ("  User@Example.COM  ", "user@example.com"),
        ("FIRST.LAST+FILTER@DOMAIN.CO.UK", "first.last+filter@domain.co.uk"),
        ("\tCandidate.Name@subdomain.example.org\n", "candidate.name@subdomain.example.org"),
        ("dev_123-test@company.io", "dev_123-test@company.io"),
    ],
)
def test_normalize_email_valid_cases(raw_input: str, expected_canonical: str) -> None:
    canonical, meta = normalize_email_address(raw_input)
    assert canonical == expected_canonical
    assert meta["is_valid"] is True
    assert meta["original"] == raw_input
    assert meta["canonical"] == expected_canonical


@pytest.mark.parametrize(
    "invalid_input",
    [
        "",
        "   ",
        None,
        12345,
        "not-an-email",
        "@example.com",
        "user@",
        "user@example",
        "user name@example.com",
        "user@@example.com",
        "user@.com",
    ],
)
def test_normalize_email_invalid_or_missing_cases(invalid_input: Any) -> None:
    canonical, meta = normalize_email_address(invalid_input)
    assert canonical is None
    assert meta["is_valid"] is False
    assert meta["original"] == invalid_input
    assert "reason" in meta


def test_normalize_email_with_audit() -> None:
    audit = NormalizationAudit()
    assert normalize_email("  Harshini.CS@Example.COM  ", audit) == "harshini.cs@example.com"
    assert normalize_email("invalid_email", audit) is None

    changes = {c["field"]: c for c in audit.changes}
    assert "email" in changes
    assert changes["email"]["source"] == "  Harshini.CS@Example.COM  "
    assert changes["email"]["canonical"] == "harshini.cs@example.com"


# ==============================================================================
# 2. Phone Normalization Tests (phonenumbers Library)
# ==============================================================================


@pytest.mark.parametrize(
    "raw_input, expected_canonical, expected_country_code",
    [
        # India standard 10-digit mobile (default region IN)
        ("9876543210", "+919876543210", 91),
        ("9159725713", "+919159725713", 91),
        ("  9876543210  ", "+919876543210", 91),
        # India explicit country code with formatting
        ("+91 98765 43210", "+919876543210", 91),
        ("+91-98765-43210", "+919876543210", 91),
        ("+91 (0) 98765 43210", "+919876543210", 91),
        # United States / North America (+1)
        ("+1 415 555 2671", "+14155552671", 1),
        ("+1 (650) 234-5678", "+16502345678", 1),
        ("+1-800-555-0199", "+18005550199", 1),
        # United Kingdom (+44)
        ("+44 20 7946 0958", "+442079460958", 44),
        ("0044 20 7946 0958", "+442079460958", 44),  # Standard European international prefix
        # Singapore (+65)
        ("+65 6789 0123", "+6567890123", 65),
        # Germany (+49)
        ("+49 30 1234567", "+49301234567", 49),
    ],
)
def test_normalize_phone_valid_cases(
    raw_input: str, expected_canonical: str, expected_country_code: int
) -> None:
    canonical, meta = normalize_phone_number(raw_input)
    assert canonical == expected_canonical
    assert meta["is_valid"] is True
    assert meta["country_code"] == expected_country_code
    assert meta["original"] == raw_input
    assert meta["canonical"] == expected_canonical


@pytest.mark.parametrize(
    "invalid_input",
    [
        "",
        "   ",
        None,
        "not-a-number",
        "123",
        "12345",
        "1234567890",           # Dummy sequential digits
        "0000000000",           # Dummy repeating zeros
        "9999999999",           # Dummy repeating nines
        "+91 XXXXX XXXXX",      # Masked placeholder
        "+91-XXXXXXXXXX",       # Masked placeholder
        [],
        {},
    ],
)
def test_normalize_phone_invalid_or_missing_cases(invalid_input: Any) -> None:
    canonical, meta = normalize_phone_number(invalid_input)
    assert canonical is None
    assert meta["is_valid"] is False
    assert meta["original"] == invalid_input
    assert "reason" in meta


def test_normalize_phone_dict_support() -> None:
    # Some ATS systems or SDKs return a structured phone dict
    payload = {"formattedNumber": "+91 98765 43210", "rawText": "9876543210"}
    canonical, meta = normalize_phone_number(payload)
    assert canonical == "+919876543210"
    assert meta["is_valid"] is True
    assert meta["country_code"] == 91


def test_normalize_phone_with_audit() -> None:
    audit = NormalizationAudit()
    assert normalize_phone("+91-98765-43210", audit) == "+919876543210"
    assert normalize_phone("9876543210", audit) == "+919876543210"
    assert normalize_phone("invalid", audit) is None

    changes = [c for c in audit.changes if c["field"] == "phone"]
    assert len(changes) >= 1
    assert changes[0]["canonical"] == "+919876543210"


# ==============================================================================
# 3. Candidate Name Normalization Tests
# ==============================================================================


@pytest.mark.parametrize(
    "raw_input, expected_canonical",
    [
        ("john doe", "John Doe"),
        ("  JANE   DOE  ", "Jane Doe"),
        ("HARSHINI CS", "Harshini CS"),          # Preserves uppercase 2-letter initials
        ("ARUN KUMAR K.", "Arun Kumar K."),       # Preserves dot initials
        ("MARY-JANE WATSON", "Mary-Jane Watson"), # Preserves hyphens
        ("jean-luc godard", "Jean-Luc Godard"),
        ("conor o'brien", "Conor O'Brien"),       # Preserves apostrophes
        ("Dr. John Smith, PhD", "John Smith"),    # Strips Dr. and PhD
        ("Prof. Alice Wonderland, MD", "Alice Wonderland"),
        ("Robert Downey Jr.", "Robert Downey Jr."), # Preserves Jr.
        ("King George III", "King George III"),   # Preserves Roman numerals
        ("Mary Jane (MJ)", "Mary Jane"),          # Strips bracketed nickname
        ("Bob Smith [Contractor]", "Bob Smith"),
    ],
)
def test_normalize_name_valid_cases(raw_input: str, expected_canonical: str) -> None:
    canonical, meta = normalize_candidate_name(raw_input)
    assert canonical == expected_canonical
    assert meta["is_valid"] is True
    assert meta["original"] == raw_input
    assert meta["canonical"] == expected_canonical


@pytest.mark.parametrize(
    "invalid_input",
    [
        "",
        "   ",
        None,
        12345,
        "---",
        "...",
        "@#$%",
        "12345678",
        "Resume",
        "Curriculum Vitae",
        "CV",
        "Biodata",
        "Candidate Profile",
        "N/A",
        "NA",
        "Unknown",
        "None",
    ],
)
def test_normalize_name_invalid_or_missing_cases(invalid_input: Any) -> None:
    canonical, meta = normalize_candidate_name(invalid_input)
    assert canonical is None
    assert meta["is_valid"] is False
    assert meta["original"] == invalid_input
    assert "reason" in meta


def test_normalize_name_with_audit() -> None:
    audit = NormalizationAudit()
    assert normalize_name("  harshini cs  ", audit) == "Harshini CS"
    assert normalize_name("Resume", audit) is None

    changes = [c for c in audit.changes if c["field"] == "candidate_name"]
    assert len(changes) >= 1
    assert changes[0]["canonical"] == "Harshini CS"


# ==============================================================================
# 4. Unified Identity Normalization & Preservation of Originals
# ==============================================================================


def test_normalize_candidate_identity_preserves_both_raw_and_canonical() -> None:
    raw_name = "  HARSHINI  CS  "
    raw_email = "  HARSHINI.CS@EXAMPLE.COM  "
    raw_phone = "+91 (987) 654-3210"

    result = normalize_candidate_identity(raw_name, raw_email, raw_phone)

    # Check canonical fields
    assert result["candidate_name"] == "Harshini CS"
    assert result["email"] == "harshini.cs@example.com"
    assert result["phone"] == "+919876543210"

    # Check preserved raw fields
    assert result["raw_candidate_name"] == raw_name
    assert result["raw_email"] == raw_email
    assert result["raw_phone"] == raw_phone

    # Check structured identity metadata
    id_meta = result["identity_metadata"]
    assert id_meta["candidate_name"]["original"] == raw_name
    assert id_meta["candidate_name"]["canonical"] == "Harshini CS"
    assert id_meta["candidate_name"]["is_valid"] is True

    assert id_meta["email"]["original"] == raw_email
    assert id_meta["email"]["canonical"] == "harshini.cs@example.com"
    assert id_meta["email"]["is_valid"] is True

    assert id_meta["phone"]["original"] == raw_phone
    assert id_meta["phone"]["canonical"] == "+919876543210"
    assert id_meta["phone"]["country_code"] == 91
    assert id_meta["phone"]["is_valid"] is True


def test_normalize_candidate_identity_handles_all_none_safely() -> None:
    result = normalize_candidate_identity(None, None, None)

    assert result["candidate_name"] is None
    assert result["email"] is None
    assert result["phone"] is None

    assert result["raw_candidate_name"] is None
    assert result["raw_email"] is None
    assert result["raw_phone"] is None

    assert result["identity_metadata"]["candidate_name"]["is_valid"] is False
    assert result["identity_metadata"]["email"]["is_valid"] is False
    assert result["identity_metadata"]["phone"]["is_valid"] is False


# ==============================================================================
# 5. ResumeNormalizer Integration Tests (Manual Upload Flow)
# ==============================================================================


def test_resume_normalizer_integrates_identity_fields() -> None:
    normalizer = ResumeNormalizer()

    extracted = SimpleNamespace(
        candidate_name="  john doe  ",
        email="  JOHN.DOE@GMAIL.COM  ",
        phone="9876543210",
        designation="Software Engineer",
        location="Bangalore, India",
        skills=["Python", "FastAPI"],
        education=[],
        experience=[],
        projects=[],
        companies=[],
        certifications=[],
        languages=[],
    )

    normalized = normalizer.normalize(extracted)

    assert normalized["phone"] == "+919876543210"
    assert normalized["email"] == "john.doe@gmail.com"

    # Verify identity metadata is preserved inside normalization_metadata
    meta = normalized["normalization_metadata"]
    assert "identity" in meta
    id_data = meta["identity"]

    assert id_data["candidate_name"]["canonical"] == "John Doe"
    assert id_data["candidate_name"]["original"] == "  john doe  "

    assert id_data["email"]["canonical"] == "john.doe@gmail.com"
    assert id_data["email"]["original"] == "  JOHN.DOE@GMAIL.COM  "

    assert id_data["phone"]["canonical"] == "+919876543210"
    assert id_data["phone"]["original"] == "9876543210"
    assert id_data["phone"]["country_code"] == 91


# ==============================================================================
# 6. Zoho Recruit Identity Ingestion Simulation Tests
# ==============================================================================


def test_zoho_recruit_identity_simulation() -> None:
    # Simulates candidate record fetched from Zoho Recruit API
    zoho_record = {
        "First_Name": "Jane",
        "Last_Name": "Doe",
        "Full_Name": "JANE DOE",
        "Email": "  Jane.Doe@Zoho.COM  ",
        "Mobile": "+1 415 555 2671",
        "Phone": None,
    }

    identity = normalize_candidate_identity(
        candidate_name=zoho_record["Full_Name"],
        email=zoho_record["Email"],
        phone=zoho_record["Mobile"],
    )

    assert identity["candidate_name"] == "Jane Doe"
    assert identity["email"] == "jane.doe@zoho.com"
    assert identity["phone"] == "+14155552671"
    assert identity["identity_metadata"]["phone"]["country_code"] == 1

    # Raw values are strictly preserved
    assert identity["raw_candidate_name"] == "JANE DOE"
    assert identity["raw_email"] == "  Jane.Doe@Zoho.COM  "
    assert identity["raw_phone"] == "+1 415 555 2671"
