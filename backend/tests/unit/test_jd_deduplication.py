import pytest
from uuid import uuid4
from unittest.mock import AsyncMock

from app.services.jd_extraction_service import (
    JDExtractionService,
    _extract_responsibilities,
    _deduplicate_responsibilities,
    _deduplicate_skills,
    _deduplicate_strings,
    _responsibility_semantic_key,
    _extract_experience,
    _extract_education,
)
from app.services.jd_normalization_service import (
    JDNormalizationService,
    _canonicalize_skills,
)


CLOUDOPS_JD_WITH_DUPLICATES = """
Role: Senior CloudOps Engineer
Company: CloudScale Solutions

Roles & Responsibilities:
- Will be responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana).
- Deploy and maintain highly available Kubernetes clusters on AWS and Azure.
- Automate CI/CD pipelines using GitHub Actions and Terraform for infrastructure as code.
- Ensure 99.99% system uptime and respond to production incidents.
- Will be responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana).
- Responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana)
- Deploying and maintaining highly available Kubernetes clusters on AWS and Azure.
- Troubleshoot production incidents and optimize Kubernetes clusters on AWS.
- Configure alerting rules and dashboards in Prometheus and Datadog.

What You Bring:
- 6–8 years of experience in Cloud Operations or DevOps engineering.
- Deep expertise in AWS, Docker, Kubernetes, k8s, Terraform, and Linux administration.
- Hands-on experience with Prometheus, Grafana, Datadog, and datadog monitoring.
- Strong scripting skills in Python, python, and Bash.
- PostgreSQL and postgres database management.

Preferred Skills:
- Experience with Kafka, Redis, and Elasticsearch.
- AWS Certified Solutions Architect or CKA certification.
"""


ZOHO_HTML_NORMALIZED_JD_WITH_DUPLICATES = """
Title: DevOps Lead
Location: Remote

Job Summary:
Lead cloud transformation and platform automation.

Responsibilities:
- Build and maintain CI/CD pipelines using GitLab CI and Docker.
- Building and maintaining CI/CD pipelines using GitLab CI and Docker
- Manage Kubernetes infrastructure across multiple AWS regions.
- Troubleshoot Kubernetes network policies and cluster security.

Required Skills:
- Docker, docker, Kubernetes, k8s, Terraform, terraform
- JavaScript, js, TypeScript, ts
- 5 to 7 years of DevOps experience

Preferred Skills:
- Helm, ArgoCD, Prometheus
"""


def test_exact_duplicate_responsibilities_removal() -> None:
    """Task 1: Exact duplicate responsibilities with surrounding punctuation/whitespace differences must be removed."""
    raw_duties = [
        "- Deploy and maintain highly available Kubernetes clusters on AWS and Azure.",
        "Deploy and maintain highly available Kubernetes clusters on AWS and Azure",
        "  Deploy and maintain highly available Kubernetes clusters on AWS and Azure.  ",
        "- Automate CI/CD pipelines using GitHub Actions and Terraform for infrastructure as code.",
    ]
    deduped = _deduplicate_responsibilities(raw_duties)
    assert len(deduped) == 2
    # Preserves first occurrence wording
    assert deduped[0] == "- Deploy and maintain highly available Kubernetes clusters on AWS and Azure."
    assert deduped[1] == "- Automate CI/CD pipelines using GitHub Actions and Terraform for infrastructure as code."


def test_semantically_equivalent_responsibilities_removal() -> None:
    """
    Task 2: Semantically equivalent responsibility statements with verb inflections
    or leading filler prefixes must be deduplicated deterministically.
    """
    raw_duties = [
        "Will be responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana).",
        "Responsible for monitoring tools and dashboards (Datadog, Prometheus, Grafana)",
        "Monitor tools and dashboards (Datadog, Prometheus, Grafana).",
        "Deploy and maintain highly available Kubernetes clusters on AWS and Azure.",
        "Deploying and maintaining highly available Kubernetes clusters on AWS and Azure.",
    ]
    deduped = _deduplicate_responsibilities(raw_duties)
    assert len(deduped) == 2
    assert "monitoring tools and dashboards" in deduped[0].lower()
    assert "kubernetes clusters on aws and azure" in deduped[1].lower()


def test_distinct_responsibilities_sharing_keywords_preserved() -> None:
    """
    Task 2 & 3: Distinct responsibilities sharing similar keywords (e.g. Kubernetes, AWS, Datadog)
    must NOT be merged.
    """
    duties = [
        "Deploy and maintain highly available Kubernetes clusters on AWS and Azure.",
        "Troubleshoot production incidents and optimize Kubernetes clusters on AWS.",
        "Configure alerting rules and dashboards in Prometheus and Datadog.",
        "Monitor tools and dashboards using Prometheus and Datadog.",
    ]
    deduped = _deduplicate_responsibilities(duties)
    # All 4 duties represent distinct operational actions and scopes
    assert len(deduped) == 4
    assert duties[0] in deduped
    assert duties[1] in deduped
    assert duties[2] in deduped
    assert duties[3] in deduped


def test_duplicate_skills_and_canonical_aliases() -> None:
    """
    Task 3: Duplicate skills and confirmed aliases (e.g., Kubernetes/k8s, PostgreSQL/postgres, JS/JavaScript)
    must be deduplicated without loss of unique skills.
    """
    raw_skills = [
        "Kubernetes", "k8s", "Docker", "docker", "AWS", "aws", "amazon web services",
        "PostgreSQL", "postgres", "psql", "JavaScript", "js", "TypeScript", "ts",
        "Terraform", "Prometheus", "Grafana", "Datadog"
    ]
    deduped = _deduplicate_skills(raw_skills)

    # Verify no duplicate canonical representations
    canonical_keys = set()
    for s in deduped:
        key = s.casefold()
        assert key not in canonical_keys, f"Duplicate skill key found: {key}"
        canonical_keys.add(key)

    # Verify unique skills are all represented
    expected_unique = {"kubernetes", "docker", "aws", "postgresql", "javascript", "typescript", "terraform", "prometheus", "grafana", "datadog"}
    for exp in expected_unique:
        assert exp in canonical_keys, f"Expected unique skill {exp} not present in deduplicated set"

    assert len(deduped) == len(expected_unique)


def test_full_pipeline_deduplication_cloudops_jd() -> None:
    """
    Test complete extraction pipeline with CloudOps JD containing repeated duties and alias skills:
    1. Duplicate responsibilities removed.
    2. Distinct responsibilities sharing keywords preserved.
    3. Duplicate skills and aliases removed.
    4. Education stays empty (Phase 4 rule).
    5. Experience range preserved without sub-span duplicates.
    6. Required and preferred skills distinct.
    """
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    ai_extractor = AsyncMock()
    ai_extractor.extract = AsyncMock(return_value=None)

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo, ai_extractor)

    import asyncio
    extracted = asyncio.run(service.extract_from_raw_text(CLOUDOPS_JD_WITH_DUPLICATES, uuid4()))

    # 1. Responsibilities: duplicates removed, distinct duties preserved
    monitoring_resps = [r for r in extracted.responsibilities if "monitoring tools and dashboards" in r.lower()]
    assert len(monitoring_resps) == 1, f"Expected exactly 1 monitoring responsibility, got: {monitoring_resps}"

    k8s_deploy_resps = [r for r in extracted.responsibilities if "deploy and maintain" in r.lower() or "deploying and maintaining" in r.lower()]
    assert len(k8s_deploy_resps) == 1, f"Expected exactly 1 deploy k8s responsibility, got: {k8s_deploy_resps}"

    # Distinct troubleshooting duty must be preserved
    assert any("troubleshoot production incidents" in r.lower() for r in extracted.responsibilities)

    # Distinct alerting rule duty must be preserved
    assert any("configure alerting rules" in r.lower() for r in extracted.responsibilities)

    # 2. Skills: exact duplicates & aliases deduplicated in required_skills
    req_skills_lower = [s.lower() for s in extracted.required_skills]
    assert req_skills_lower.count("kubernetes") == 1
    assert "k8s" not in req_skills_lower
    assert req_skills_lower.count("python") == 1

    # 3. Education: correctly empty
    assert extracted.education == []

    # 4. Experience: exact range preserved without duplicate '8 years'
    assert any("6–8 years" in e for e in extracted.experience)
    assert not any(e.strip() == "8 years of experience" for e in extracted.experience)

    # 5. Required vs Preferred: distinct
    assert any("kafka" in s.lower() for s in extracted.preferred_skills)
    assert not any("kafka" in s.lower() for s in extracted.required_skills)


def test_plain_text_and_zoho_html_normalized_jd_compatibility() -> None:
    """Task 5: Plain-text and Zoho HTML-normalized JDs deduplicate cleanly."""
    doc_repo = AsyncMock()
    parsed_repo = AsyncMock()
    extracted_repo = AsyncMock()
    ai_extractor = AsyncMock()
    ai_extractor.extract = AsyncMock(return_value=None)

    service = JDExtractionService(doc_repo, parsed_repo, extracted_repo, ai_extractor)

    import asyncio
    extracted = asyncio.run(service.extract_from_raw_text(ZOHO_HTML_NORMALIZED_JD_WITH_DUPLICATES, uuid4()))

    # Exactly 1 CI/CD pipeline responsibility (exact & verb duplicate removed)
    cicd_resps = [r for r in extracted.responsibilities if "ci/cd" in r.lower()]
    assert len(cicd_resps) == 1

    # Distinct K8s troubleshooting preserved
    assert any("troubleshoot kubernetes" in r.lower() for r in extracted.responsibilities)
    assert any("manage kubernetes" in r.lower() for r in extracted.responsibilities)

    # Skills deduplicated
    req_skills_lower = [s.lower() for s in extracted.required_skills]
    assert req_skills_lower.count("docker") == 1
    assert req_skills_lower.count("kubernetes") == 1
    assert "k8s" not in req_skills_lower
    assert req_skills_lower.count("javascript") == 1
    assert "js" not in req_skills_lower


def test_stable_output_ordering_and_repeatability() -> None:
    """Task 5: Output ordering must be stable and deterministic across multiple runs."""
    duties = [
        "First responsibility: deploy microservices.",
        "Second responsibility: maintain monitoring dashboards.",
        "Third responsibility: automate testing pipelines.",
        "First responsibility: deploy microservices.",  # duplicate
    ]
    run1 = _deduplicate_responsibilities(duties)
    run2 = _deduplicate_responsibilities(duties)
    assert run1 == run2
    assert run1 == [
        "First responsibility: deploy microservices.",
        "Second responsibility: maintain monitoring dashboards.",
        "Third responsibility: automate testing pipelines.",
    ]

    skills = ["Python", "Docker", "AWS", "python", "docker", "Kubernetes", "k8s"]
    s_run1 = _deduplicate_skills(skills)
    s_run2 = _deduplicate_skills(skills)
    assert s_run1 == s_run2
    assert s_run1 == ["Python", "Docker", "AWS", "Kubernetes"]
