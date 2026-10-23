from __future__ import annotations

import pytest
from uuid import uuid4
from unittest.mock import MagicMock

from app.services.zoho_recruit_service import (
    HTMLToTextParser,
    ZohoJobOpening,
    _job_opening,
    normalize_html_to_text,
)
from app.services.jd_extraction_service import JDExtractionService


# -------------------------------------------------------------------------------------------------
# 1. HTML descriptions containing headings and bullet lists
# -------------------------------------------------------------------------------------------------
def test_html_with_headings_and_bullet_lists() -> None:
    raw_html = """
    <div>
        <h2>Senior Software Engineer</h2>
        <p>We are seeking an engineer to join our backend team.</p>
        <h3>Required Skills:</h3>
        <ul>
            <li>Python</li>
            <li>FastAPI</li>
            <li>PostgreSQL</li>
        </ul>
        <h3>Responsibilities:</h3>
        <ul>
            <li>Design and build scalable microservices</li>
            <li>Collaborate with product and QA teams</li>
        </ul>
    </div>
    """
    text = normalize_html_to_text(raw_html)
    assert text is not None

    # Verify headings are present as clean lines
    assert "Senior Software Engineer" in text
    assert "Required Skills:" in text
    assert "Responsibilities:" in text

    # Verify bullet lists are formatted with '-' prefixes
    assert "- Python" in text
    assert "- FastAPI" in text
    assert "- PostgreSQL" in text
    assert "- Design and build scalable microservices" in text
    assert "- Collaborate with product and QA teams" in text

    # Verify no raw HTML tags remain
    assert "<" not in text
    assert ">" not in text


# -------------------------------------------------------------------------------------------------
# 2. HTML entities and special characters
# -------------------------------------------------------------------------------------------------
def test_html_entities_and_special_characters() -> None:
    raw_html = (
        "<p>FastAPI &amp; RESTful APIs &nbsp; development &bull; "
        "Candidate&#39;s experience with &quot;Python 3.12+&quot; &lt;backend&gt; &amp; tools.</p>"
    )
    text = normalize_html_to_text(raw_html)
    assert text is not None

    assert "&amp;" not in text
    assert "&nbsp;" not in text
    assert "&#39;" not in text
    assert "&quot;" not in text
    assert "&lt;" not in text
    assert "&gt;" not in text

    assert "FastAPI & RESTful APIs development" in text
    assert "Candidate's experience with \"Python 3.12+\"" in text
    assert "<backend>" in text or "backend" in text


# -------------------------------------------------------------------------------------------------
# 3. HTML descriptions without explicit newlines (minified/single-line markup)
# -------------------------------------------------------------------------------------------------
def test_html_without_explicit_newlines() -> None:
    minified_html = (
        "<div><p>About the Job:</p><p>We are hiring immediately.</p>"
        "<p><strong>Required Skills:</strong></p>"
        "<ul><li>Docker</li><li>Kubernetes</li><li>CI/CD</li></ul>"
        "<p><strong>Education:</strong></p>"
        "<p>B.Tech in Computer Science</p></div>"
    )
    text = normalize_html_to_text(minified_html)
    assert text is not None

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    assert "About the Job:" in lines
    assert "We are hiring immediately." in lines
    assert "Required Skills:" in lines
    assert "- Docker" in lines
    assert "- Kubernetes" in lines
    assert "- CI/CD" in lines
    assert "Education:" in lines
    assert "B.Tech in Computer Science" in lines


# -------------------------------------------------------------------------------------------------
# 4. Empty and malformed HTML
# -------------------------------------------------------------------------------------------------
def test_empty_and_malformed_html() -> None:
    assert normalize_html_to_text(None) is None
    assert normalize_html_to_text("") == ""
    assert normalize_html_to_text("   \n\t  ") == ""

    # Unclosed tags
    unclosed = "<div><p>Unclosed paragraph and <strong>bold text without closing tag"
    clean_unclosed = normalize_html_to_text(unclosed)
    assert clean_unclosed is not None
    assert "Unclosed paragraph and bold text without closing tag" in clean_unclosed
    assert "<" not in clean_unclosed

    # Stray angle brackets and broken entity
    stray = "Mathematical condition: x < 10 and y > 20 &unknownentity;"
    clean_stray = normalize_html_to_text(stray)
    assert clean_stray is not None
    assert "x < 10 and y > 20" in clean_stray or "x" in clean_stray


# -------------------------------------------------------------------------------------------------
# 5. Existing plain-text JDs, ensuring backward compatibility
# -------------------------------------------------------------------------------------------------
def test_plain_text_backward_compatibility() -> None:
    plain_text = (
        "Job Title: Senior Backend Engineer\n\n"
        "Required Skills:\n"
        "- Python\n"
        "- FastAPI\n"
        "- PostgreSQL\n\n"
        "Responsibilities:\n"
        "- Develop REST APIs\n"
        "- Maintain database schemas"
    )
    result = normalize_html_to_text(plain_text)
    assert result == plain_text


# -------------------------------------------------------------------------------------------------
# 6. Automatic normalization in ZohoJobOpening parser
# -------------------------------------------------------------------------------------------------
def test_job_opening_parser_normalizes_fields() -> None:
    raw_item = {
        "id": "9001",
        "Job_Opening_ID": "JOB_9001",
        "Posting_Title": "Lead DevOps Engineer",
        "Job_Description": "<p><strong>Overview:</strong></p><ul><li>Manage cloud infra</li><li>Maintain pipelines</li></ul>",
        "Required_Skills": "<p>Terraform &amp; Kubernetes</p>",
        "Job_Opening_Status": "In-progress",
    }
    job = _job_opening(raw_item)
    assert isinstance(job, ZohoJobOpening)
    assert "<p>" not in (job.job_description or "")
    assert "<ul>" not in (job.job_description or "")
    assert "Overview:" in (job.job_description or "")
    assert "- Manage cloud infra" in (job.job_description or "")
    assert "- Maintain pipelines" in (job.job_description or "")

    assert "<p>" not in (job.required_skills or "")
    assert "Terraform & Kubernetes" in (job.required_skills or "")


# -------------------------------------------------------------------------------------------------
# 7. Successful extraction of skills and responsibilities from a representative Zoho JD
# -------------------------------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_successful_extraction_from_representative_zoho_jd() -> None:
    zoho_html_jd = """
    <div>
        <h2>Senior Python Developer</h2>
        <p><strong>Job Overview:</strong> We are seeking a talented Senior Python Developer to join our team.</p>
        
        <p><strong>Required Skills:</strong></p>
        <ul>
            <li>Python</li>
            <li>FastAPI &amp; REST APIs</li>
            <li>PostgreSQL &nbsp; and Redis</li>
            <li>Docker &amp; Kubernetes</li>
        </ul>

        <p><strong>Responsibilities:</strong></p>
        <ul>
            <li>Architect and develop high performance microservices using FastAPI.</li>
            <li>Collaborate with cross-functional teams to define architecture and specifications.</li>
            <li>Design robust database schemas and optimize PostgreSQL queries.</li>
        </ul>

        <p><strong>Education:</strong></p>
        <ul>
            <li>Bachelor of Technology in Computer Science or related field.</li>
        </ul>

        <p><strong>Experience:</strong></p>
        <ul>
            <li>3+ years of professional experience in backend software engineering.</li>
        </ul>
    </div>
    """

    # Normalize HTML to plain text
    clean_text = normalize_html_to_text(zoho_html_jd)
    assert clean_text is not None

    # Feed into JDExtractionService
    service = JDExtractionService(MagicMock(), MagicMock(), MagicMock())
    extracted = await service.extract_from_raw_text(clean_text, uuid4())

    # Verify extracted structured fields
    assert extracted.job_title == "Senior Python Developer"

    # Skills detection
    assert "Python" in extracted.required_skills
    assert any("FastAPI" in s for s in extracted.required_skills)
    assert any("PostgreSQL" in s for s in extracted.required_skills)
    assert any("Docker" in s for s in extracted.required_skills)

    # Responsibilities detection
    assert len(extracted.responsibilities) >= 2
    assert any("microservices" in r.lower() for r in extracted.responsibilities)
    assert any("collaborate" in r.lower() for r in extracted.responsibilities)

    # Education detection
    assert len(extracted.education) >= 1
    assert any("bachelor" in e.lower() for e in extracted.education)

    # Experience detection
    assert len(extracted.experience) >= 1
    assert any("3" in exp for exp in extracted.experience)
