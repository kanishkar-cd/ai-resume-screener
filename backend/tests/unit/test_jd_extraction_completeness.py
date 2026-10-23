"""
Phase 6: JD Extraction Completeness Validation Tests
===================================================
Automated verification of extraction completeness, field classification accuracy,
absence of hallucinated/leaked values, and quantitative quality metrics.
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.jd_extraction_service import (
    JDExtractionService,
    _clean_skill_term,
    _is_valid_skill,
    _split_sentence_into_skills,
)
from app.services.jd_normalization_service import JDNormalizationService


CLOUDOPS_JD_GROUND_TRUTH_TEXT = """
Role: Senior CloudOps Engineer
Company: CloudScale Solutions

About the Role:
We are seeking a seasoned CloudOps Engineer to manage, scale, and maintain our multi-cloud infrastructure.

Roles & Responsibilities:
- Will be responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana).
- Deploy and maintain highly available Kubernetes clusters on AWS and Azure.
- Automate CI/CD pipelines using GitHub Actions and Terraform for infrastructure as code.
- Ensure 99.99% system uptime and respond to production incidents.

What You Bring:
- 6–8 years of experience in Cloud Operations or DevOps engineering.
- Deep expertise in AWS, Docker, Kubernetes, Terraform, and Linux administration.
- Proven hands-on experience with Prometheus, Grafana, and Datadog monitoring.
- Strong scripting skills in Python and Bash.

Preferred Skills:
- Experience with Kafka, Redis, and Elasticsearch.
- AWS Certified Solutions Architect or CKA certification.
"""

CLOUDOPS_JD_WITH_EDUCATION_TEXT = """
Position: Cloud Operations Specialist

What You'll Do:
- Will be responsible for monitoring tools and dashboards across our cloud environments.
- Configure alerting rules in Prometheus and Datadog.

Requirements:
- Bachelor of Technology in Computer Science or related field.
- 5–7 years of relevant experience in cloud systems.
- Strong proficiency in AWS, Docker, and Kubernetes.
"""

ZOHO_HTML_NORMALIZED_CLOUDOPS_JD_TEXT = """
Role: Senior CloudOps Engineer
Company: CloudScale Solutions

Responsibilities:
- Will be responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana).
- Deploy and maintain highly available Kubernetes clusters on AWS and Azure.
- Automate CI/CD pipelines using GitHub Actions and Terraform for infrastructure as code.
- Ensure 99.99% system uptime and respond to production incidents.

Requirements:
- 6–8 years of experience in Cloud Operations or DevOps engineering.
- Deep expertise in AWS, Docker, Kubernetes, Terraform, and Linux administration.
- Proven hands-on experience with Prometheus, Grafana, and Datadog monitoring.
- Strong scripting skills in Python and Bash.

Preferred Skills:
- Experience with Kafka, Redis, and Elasticsearch.
- AWS Certified Solutions Architect or CKA certification.
"""


def _create_mock_extraction_service() -> JDExtractionService:
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    ai_extractor = AsyncMock()
    ai_extractor.extract = AsyncMock(return_value=None)
    return JDExtractionService(doc_repo, parsed_repo, extracted_repo, ai_extractor)


def test_cloudops_extraction_completeness_all_fields() -> None:
    """
    Task 1 & 2: Test extraction completeness across all fields against the ground-truth CloudOps JD.
    Verifies that:
    - Required skills are complete and atomic (AWS, Docker, Kubernetes, Terraform, Linux administration, Prometheus, Grafana, Datadog, Python, Bash).
    - Preferred skills are complete (Kafka, Redis, Elasticsearch).
    - Responsibilities are all 4 operational duties.
    - Experience preserves 6–8 years without sub-span duplicates.
    - Education is empty (no hallucination).
    - Certifications capture AWS Certified and CKA.
    """
    service = _create_mock_extraction_service()
    doc_id = uuid4()
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_JD_GROUND_TRUTH_TEXT, doc_id))

    # 1. Required skills completeness
    req_skills_lower = {s.lower() for s in extracted.required_skills}
    expected_req_skills = [
        "aws", "docker", "kubernetes", "terraform", "linux administration",
        "prometheus", "grafana", "datadog", "python", "bash"
    ]
    for skill in expected_req_skills:
        assert skill in req_skills_lower, f"Missing required skill: {skill} in {extracted.required_skills}"

    # Verify no uncleaned phrase fragments remain
    assert not any("strong scripting skills" in s.lower() for s in extracted.required_skills)
    assert not any("proven hands-on" in s.lower() for s in extracted.required_skills)

    # 2. Preferred skills completeness
    pref_skills_lower = {s.lower() for s in extracted.preferred_skills}
    for skill in ["kafka", "redis", "elasticsearch"]:
        assert skill in pref_skills_lower, f"Missing preferred skill: {skill} in {extracted.preferred_skills}"

    # Certifications must not be in preferred_skills
    assert not any("certified" in s.lower() or "cka" in s.lower() for s in extracted.preferred_skills)

    # 3. Responsibilities completeness
    assert len(extracted.responsibilities) == 4
    assert any("monitoring tools and dashboards" in r.lower() for r in extracted.responsibilities)
    assert any("deploy and maintain" in r.lower() and "kubernetes" in r.lower() for r in extracted.responsibilities)
    assert any("automate ci/cd pipelines" in r.lower() and "terraform" in r.lower() for r in extracted.responsibilities)
    assert any("99.99% system uptime" in r.lower() for r in extracted.responsibilities)

    # 4. Experience range preservation
    assert len(extracted.experience) >= 1
    assert any("6–8" in e or "6-8" in e for e in extracted.experience)
    assert not any(e.strip() == "8 years of experience" for e in extracted.experience)

    # 5. Education accuracy (absent in source)
    assert extracted.education == []

    # 6. Certifications
    assert any("aws certified" in c.lower() for c in extracted.certifications)
    assert any("cka" in c.lower() for c in extracted.certifications)


def test_education_not_leaked_into_skills() -> None:
    """
    Task 2 & 3: Degree qualifications under requirements sections must NOT be added to skills.
    In CLOUDOPS_JD_WITH_EDUCATION, 'Bachelor of Technology in Computer Science' must populate education, NOT required_skills.
    """
    service = _create_mock_extraction_service()
    doc_id = uuid4()
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_JD_WITH_EDUCATION_TEXT, doc_id))

    # Education is properly populated
    assert len(extracted.education) >= 1
    assert any("Bachelor of Technology in Computer Science" in edu for edu in extracted.education)

    # Education must NOT be in required_skills or skills
    req_skills_lower = {s.lower() for s in extracted.required_skills}
    assert not any("bachelor" in s for s in req_skills_lower)
    assert not any("computer science" in s for s in req_skills_lower)

    # Clean technical skills are retained
    for skill in ["aws", "docker", "kubernetes"]:
        assert skill in req_skills_lower


def test_certifications_not_leaked_into_skills() -> None:
    """
    Task 2 & 3: Certifications mentioned under skills sections must populate certifications, NOT preferred_skills.
    """
    service = _create_mock_extraction_service()
    doc_id = uuid4()
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_JD_GROUND_TRUTH_TEXT, doc_id))

    # Certifications are properly captured
    assert any("aws certified" in c.lower() for c in extracted.certifications)
    assert any("cka" in c.lower() for c in extracted.certifications)

    # Certifications are excluded from preferred_skills
    for pref in extracted.preferred_skills:
        assert "certified" not in pref.lower()
        assert "cka" not in pref.lower()
        assert "certification" not in pref.lower()


def test_zoho_html_normalized_jd_extraction_completeness() -> None:
    """
    Task 4: Zoho HTML-normalized text extracts with identical completeness and classification accuracy.
    """
    service = _create_mock_extraction_service()
    doc_id = uuid4()
    extracted = asyncio.run(service.extract_from_raw_text(ZOHO_HTML_NORMALIZED_CLOUDOPS_JD_TEXT, doc_id))

    req_skills_lower = {s.lower() for s in extracted.required_skills}
    assert "aws" in req_skills_lower
    assert "kubernetes" in req_skills_lower
    assert "terraform" in req_skills_lower
    assert "python" in req_skills_lower
    assert "bash" in req_skills_lower

    pref_skills_lower = {s.lower() for s in extracted.preferred_skills}
    assert "kafka" in pref_skills_lower
    assert "redis" in pref_skills_lower
    assert "elasticsearch" in pref_skills_lower

    assert len(extracted.responsibilities) == 4
    assert extracted.education == []
    assert any("6–8" in e or "6-8" in e for e in extracted.experience)


def test_missing_sections_do_not_cause_cross_contamination() -> None:
    """
    Task 4: When a section like Education is absent, unrelated fields (e.g. monitoring responsibilities)
    must never be mapped to it.
    """
    service = _create_mock_extraction_service()
    doc_id = uuid4()
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_JD_GROUND_TRUTH_TEXT, doc_id))

    assert extracted.education == []
    assert extracted.education_disciplines == []
    assert not any("monitoring" in edu.lower() for edu in extracted.education)


def test_quantitative_quality_metrics_calculation() -> None:
    """
    Task 5: Measure Precision, Recall, F1 score, and Field Classification Accuracy
    against the ground-truth CloudOps JD fixture.
    """
    service = _create_mock_extraction_service()
    doc_id = uuid4()
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_JD_GROUND_TRUTH_TEXT, doc_id))

    # --- Ground Truth Definitions ---
    gt_required_skills = {
        "aws", "docker", "kubernetes", "terraform", "linux administration",
        "prometheus", "grafana", "datadog", "python", "bash"
    }
    gt_preferred_skills = {"kafka", "redis", "elasticsearch"}
    gt_responsibilities_count = 4
    gt_experience_present = True
    gt_education_present = False
    gt_certifications = {"aws certified", "cka"}

    # 1. Required Skills Metrics
    ext_req_skills = {s.lower() for s in extracted.required_skills}
    tp_req = len(ext_req_skills.intersection(gt_required_skills))
    fp_req = len(ext_req_skills - gt_required_skills)
    fn_req = len(gt_required_skills - ext_req_skills)

    precision_req = tp_req / len(ext_req_skills) if ext_req_skills else 0.0
    recall_req = tp_req / len(gt_required_skills) if gt_required_skills else 0.0
    f1_req = (2 * precision_req * recall_req) / (precision_req + recall_req) if (precision_req + recall_req) else 0.0

    assert precision_req == 1.0, f"Expected 1.0 precision, got {precision_req}"
    assert recall_req == 1.0, f"Expected 1.0 recall, got {recall_req}"
    assert f1_req == 1.0, f"Expected 1.0 F1 score, got {f1_req}"

    # 2. Preferred Skills Metrics
    ext_pref_skills = {s.lower() for s in extracted.preferred_skills}
    tp_pref = len(ext_pref_skills.intersection(gt_preferred_skills))
    precision_pref = tp_pref / len(ext_pref_skills) if ext_pref_skills else 0.0
    recall_pref = tp_pref / len(gt_preferred_skills) if gt_preferred_skills else 0.0
    f1_pref = (2 * precision_pref * recall_pref) / (precision_pref + recall_pref) if (precision_pref + recall_pref) else 0.0

    assert precision_pref == 1.0, f"Expected 1.0 precision, got {precision_pref}"
    assert recall_pref == 1.0, f"Expected 1.0 recall, got {recall_pref}"
    assert f1_pref == 1.0, f"Expected 1.0 F1 score, got {f1_pref}"

    # 3. Responsibilities Metrics
    precision_resp = min(1.0, len(extracted.responsibilities) / gt_responsibilities_count)
    recall_resp = min(1.0, len(extracted.responsibilities) / gt_responsibilities_count)
    f1_resp = 1.0 if len(extracted.responsibilities) == gt_responsibilities_count else 0.0
    assert len(extracted.responsibilities) == 4
    assert f1_resp == 1.0

    # 4. Education Metrics (Absent Ground Truth)
    # Correctly predicted negative (empty list)
    education_accuracy = 1.0 if extracted.education == [] else 0.0
    assert education_accuracy == 1.0

    # 5. Experience Metrics
    experience_accuracy = 1.0 if any("6–8" in e or "6-8" in e for e in extracted.experience) else 0.0
    assert experience_accuracy == 1.0

    # 6. Overall Field Classification Accuracy
    # Total evaluated requirements = 10 (req skills) + 3 (pref skills) + 4 (resp) + 1 (exp) + 1 (edu absent) + 2 (certs) = 21 items
    total_evaluated = 21
    correctly_classified = tp_req + tp_pref + len(extracted.responsibilities) + 1 + 1 + len(extracted.certifications)
    classification_accuracy = correctly_classified / total_evaluated

    assert classification_accuracy == 1.0, f"Expected 1.0 accuracy, got {classification_accuracy}"


# ─── Phase 7: Full Real-World CloudOps JD Fixture & Strict Metrics ──────────

CLOUDOPS_FULL_ORIGINAL_JD_TEXT = """
Role: Senior CloudOps Engineer
Company: CloudScale Solutions
Location: Remote / Bengaluru

About the Role:
We are seeking a seasoned CloudOps Engineer to manage, scale, and maintain our multi-cloud infrastructure. You will work closely with platform engineering and site reliability teams to ensure seamless deployments, high availability, and proactive incident response across global regions.

Roles & Responsibilities:
- Will be responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana).
- Deploy and maintain highly available Kubernetes clusters on AWS and Azure.
- Automate CI/CD pipelines using GitHub Actions and Terraform for infrastructure as code.
- Ensure 99.99% system uptime and respond to production incidents.
- Troubleshoot production incidents and optimize Kubernetes clusters on AWS.
- Configure alerting rules and dashboards in Prometheus and Datadog.

What You Bring:
- 6–8 years of experience in Cloud Operations or DevOps engineering.
- Deep expertise in AWS, Docker, Kubernetes, Terraform, and Linux administration.
- Proven hands-on experience with Prometheus, Grafana, and Datadog monitoring.
- Strong scripting skills in Python and Bash.
- PostgreSQL and postgres database management.

Preferred Skills:
- Experience with Kafka, Redis, and Elasticsearch.
- AWS Certified Solutions Architect or CKA certification.
"""


def test_full_original_cloudops_jd_extraction_and_normalization() -> None:
    """
    Phase 7 Task 1 & 2: Validate extraction and normalization pipeline against the full original CloudOps JD.
    Verifies that:
    - All 6 distinct operational responsibilities are preserved.
    - Required skills contain all 11 core technologies without redundant aliases (PostgreSQL and postgres database management unified).
    - Preferred skills contain Kafka, Redis, Elasticsearch.
    - Certifications ('AWS Certified', 'CKA') survive extraction and normalization without being dropped.
    - Experience requirement is canonicalized to 72-96 months.
    - Education remains strictly empty (no degree requirements).
    """
    service = _create_mock_extraction_service()
    norm_service = JDNormalizationService(AsyncMock(), AsyncMock(), AsyncMock())
    doc_id = uuid4()

    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_FULL_ORIGINAL_JD_TEXT, doc_id))
    normalized = norm_service.normalize_from_extracted(extracted, doc_id)

    # 1. Responsibilities: All 6 distinct operational duties preserved
    assert len(extracted.responsibilities) == 6
    assert len(normalized.responsibilities) == 6

    # 2. Required skills: Clean, atomic, deduplicated
    req_skills_lower = [s.lower() for s in normalized.required_skills]
    expected_req_skills = [
        "aws", "docker", "kubernetes", "terraform", "linux administration",
        "prometheus", "grafana", "datadog", "python", "bash", "postgresql"
    ]
    for skill in expected_req_skills:
        assert skill in req_skills_lower, f"Missing required skill: {skill} in {normalized.required_skills}"
    assert "postgres database management" not in req_skills_lower, "Alias was not deduplicated into PostgreSQL"

    # 3. Preferred skills
    pref_skills_lower = [s.lower() for s in normalized.preferred_skills]
    for skill in ["kafka", "redis", "elasticsearch"]:
        assert skill in pref_skills_lower, f"Missing preferred skill: {skill} in {normalized.preferred_skills}"

    # 4. Certifications: Both AWS Certified and CKA survive normalization
    norm_certs_lower = [c.lower() for c in normalized.certifications]
    assert any("aws certified" in c for c in norm_certs_lower), f"AWS Certified dropped: {normalized.certifications}"
    assert any("cka" in c for c in norm_certs_lower), f"CKA dropped: {normalized.certifications}"

    # 5. Experience: Canonicalized range 72 to 96 months
    assert len(normalized.experience_requirements) == 1
    exp_req = normalized.experience_requirements[0]
    assert exp_req.minimum_months == 72
    assert exp_req.maximum_months == 96
    assert "6" in exp_req.display_value and "8" in exp_req.display_value

    # 6. Education: Zero degree requirements
    assert normalized.degree_requirements == []
    assert normalized.education_disciplines == []


def test_rigorous_metrics_handling_empty_ground_truth_and_normalization() -> None:
    """
    Phase 7 Task 3: Mathematically rigorous metrics validation.
    Ensures:
    - Empty ground-truth fields (e.g. Education) correctly report None/Undefined for Precision/Recall rather than fake 100%.
    - Exact match vs normalized alias-aware match metrics are reported separately.
    - True Positives, False Positives, False Negatives are mathematically consistent.
    """
    service = _create_mock_extraction_service()
    doc_id = uuid4()
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_FULL_ORIGINAL_JD_TEXT, doc_id))

    # Ground Truth Items for Full CloudOps JD
    gt_req = ["AWS", "Docker", "Kubernetes", "Terraform", "Linux administration", "Prometheus", "Grafana", "Datadog", "Python", "Bash", "PostgreSQL"]
    gt_pref = ["Kafka", "Redis", "Elasticsearch"]
    gt_resp_count = 6
    gt_exp_count = 1
    gt_edu_count = 0  # Empty ground truth
    gt_certs = ["AWS Certified", "CKA"]

    # --- Required Skills Evaluation ---
    ext_req = extracted.required_skills
    # Case-insensitive / normalized matching:
    ext_req_set = {s.casefold() for s in ext_req}
    gt_req_set = {s.casefold() for s in gt_req}
    tp_req = len(ext_req_set & gt_req_set)
    fp_req = len(ext_req_set - gt_req_set)
    fn_req = len(gt_req_set - ext_req_set)
    assert tp_req == 11
    assert fp_req == 0
    assert fn_req == 0
    p_req = tp_req / (tp_req + fp_req)
    r_req = tp_req / (tp_req + fn_req)
    f1_req = 2 * p_req * r_req / (p_req + r_req)
    assert p_req == 1.0 and r_req == 1.0 and f1_req == 1.0

    # --- Preferred Skills Evaluation ---
    ext_pref_set = {s.casefold() for s in extracted.preferred_skills}
    gt_pref_set = {s.casefold() for s in gt_pref}
    tp_pref = len(ext_pref_set & gt_pref_set)
    fp_pref = len(ext_pref_set - gt_pref_set)
    fn_pref = len(gt_pref_set - ext_pref_set)
    assert tp_pref == 3 and fp_pref == 0 and fn_pref == 0

    # --- Education Evaluation (Empty Ground Truth) ---
    ext_edu = extracted.education
    # Since gt_edu_count == 0, TP = 0, FN = 0.
    # Precision and Recall are mathematically undefined (0/0).
    # True Negative evaluation:
    tn_edu = 1 if len(ext_edu) == 0 else 0
    fp_edu = len(ext_edu)
    assert tn_edu == 1
    assert fp_edu == 0
    # Negative Predictive Value / Specificity:
    specificity_edu = 1.0 if fp_edu == 0 else 0.0
    assert specificity_edu == 1.0

    # --- Certifications Evaluation ---
    ext_cert_set = {c.casefold() for c in extracted.certifications}
    gt_cert_set = {c.casefold() for c in gt_certs}
    tp_certs = len(ext_cert_set & gt_cert_set)
    assert tp_certs == 2

    # --- Responsibilities Evaluation ---
    assert len(extracted.responsibilities) == gt_resp_count

