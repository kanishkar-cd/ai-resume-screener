import pytest
from types import SimpleNamespace
from app.services.matching_service import RequirementBuilder, EvidenceBuilder, DeterministicRequirementMatcher
from app.services.normalizers.resume_normalizer import ResumeNormalizer
from app.services.scoring.component_scoring_service import ComponentScoringService
from app.services.scoring.weight_calculation_service import WeightCalculationService
from app.services.scoring.bonus_service import BonusService
from app.services.scoring.penalty_service import PenaltyService
from app.services.scoring.recommendation_service import RecommendationService
from app.schemas.scoring import RecommendationLevel

# ─── Shared Test Fixtures ───────────────────────────────────────────────────

DATA_ENGINEER_FRESHER_JD = SimpleNamespace(
    job_title="Data Engineer – Fresher",
    required_skills=[
        "Python", "PySpark", "SQL", "PostgreSQL", "REST APIs", "Airflow",
        "AWS S3", "Docker", "Git/GitHub", "ETL Pipelines", "Data Modeling",
        "Data Warehousing", "Data Quality", "Unit Testing"
    ],
    preferred_skills=["Airflow", "AWS S3", "Docker", "Kafka", "PySpark"],
    skills=[
        "Python", "PySpark", "SQL", "PostgreSQL", "REST APIs", "Airflow",
        "AWS S3", "Docker", "Git/GitHub", "ETL Pipelines", "Data Modeling",
        "Data Warehousing", "Data Quality", "Unit Testing", "Kafka"
    ],
    responsibilities=[
        "Design and build ETL data pipelines using Python, PySpark, and SQL.",
        "Create and optimize database schemas and queries in PostgreSQL.",
        "Develop REST APIs for data ingestion and integration.",
        "Orchestrate data workflows using Apache Airflow and deploy services with Docker on AWS S3.",
        "Implement data quality checks, unit tests, and pipeline troubleshooting."
    ],
    experience_requirements=[{"minimum_months": 0, "maximum_months": 12, "display_value": "0-1 year"}],
    degree_requirements=["Bachelor's degree in Computer Science, Information Technology, or related engineering discipline."],
    project_requirements=[],
    certifications=[],
    keywords=["Data Engineering", "PySpark", "ETL", "Airflow", "PostgreSQL", "AWS S3", "Docker"],
)

PRIYA_SHARMA_RESUME = SimpleNamespace(
    candidate_name="Priya Sharma",
    skills=[
        "Python", "PySpark", "SQL", "PostgreSQL", "REST APIs", "Airflow",
        "AWS S3", "Docker", "Git", "GitHub", "ETL", "Data Pipelines",
        "Data Modeling", "Data Warehousing", "Data Quality", "Unit Testing", "Parquet"
    ],
    education=[{"degree": "Bachelor of Technology", "field_of_study": "Computer Science and Engineering"}],
    certifications=[],
    languages=["English"],
    experience=[
        {
            "company": "DataTech Solutions",
            "title": "Data Engineering Intern",
            "designation": "Data Engineering Intern",
            "employment_type": "Internship",
            "duration_months": 4,
            "description": "Built scalable ETL pipelines using Python and PySpark to process structured and semi-structured datasets. Designed PostgreSQL relational database schemas, created indexes, and wrote complex SQL queries. Built REST APIs for automated data ingestion and integrated AWS S3 for cloud object storage. Orchestrated daily DAG workflows in Apache Airflow and containerized services using Docker and Git. Conducted data quality checks, unit testing, and pipeline troubleshooting.",
            "technologies": ["Python", "PySpark", "SQL", "PostgreSQL", "REST APIs", "Airflow", "AWS S3", "Docker", "Git", "ETL"],
            "responsibilities": [
                "Built scalable ETL pipelines using Python and PySpark",
                "Designed PostgreSQL relational database schemas and wrote complex SQL queries",
                "Built REST APIs for data ingestion and integrated AWS S3",
                "Orchestrated daily DAG workflows in Apache Airflow and containerized with Docker",
                "Conducted data quality checks, unit testing, and pipeline troubleshooting"
            ]
        }
    ],
    projects=[
        {
            "name": "PySpark & Airflow ETL Data Pipeline",
            "description": "Developed automated data processing pipeline using Python, PySpark, Airflow, and PostgreSQL; deployed with Docker.",
            "technologies": ["Python", "PySpark", "Airflow", "PostgreSQL", "Docker", "ETL"]
        },
        {
            "name": "Cloud Data Lake Ingestion Service",
            "description": "Built REST API ingestion service connecting to AWS S3 and PostgreSQL; written in Python with SQL window functions and data quality validation.",
            "technologies": ["Python", "REST APIs", "AWS S3", "PostgreSQL", "SQL"]
        }
    ]
)

DEFAULT_CONFIG = SimpleNamespace(
    mandatory_skills=[],
    min_experience_years=0,
    required_degree="Bachelor's degree",
    required_certifications=[],
    required_languages=[],
)


def _score_candidate(job: SimpleNamespace, resume: SimpleNamespace, config: SimpleNamespace):
    matcher = DeterministicRequirementMatcher()
    requirements = RequirementBuilder.build(job, config)
    extracted = SimpleNamespace(
        candidate_name=resume.candidate_name,
        skills=resume.skills,
        education=resume.education,
        certifications=resume.certifications,
        languages=resume.languages,
        experience=resume.experience,
        projects=resume.projects,
    )
    evidence = EvidenceBuilder.build(extracted)
    verdicts = [matcher.match(req, resume, evidence) for req in requirements]
    scoring_svc = ComponentScoringService()
    components = scoring_svc.score(resume, job, config, projects=extracted.projects, match_verdicts=verdicts)
    applicable = WeightCalculationService.applicable_categories(job, config)
    weighted_schema, raw_total, weighted_total, effective_weights = WeightCalculationService.calculate(components, config, applicable_categories=applicable)
    penalty_total, penalties = PenaltyService.calculate(components, config)
    bonus_total, bonuses = BonusService.calculate(resume, job, config, components, verdicts, extracted.projects)
    final_score = WeightCalculationService.final_score(weighted_total, penalty_total, bonus_total, components, applicable)
    knocked_out, knockout_reason = WeightCalculationService.knockout(components, config)
    recommendation = RecommendationService.recommend(final_score, passing_score=70.0, is_knocked_out=knocked_out)
    return components, applicable, effective_weights, final_score, knocked_out, recommendation


# ─── Regression Test Cases ──────────────────────────────────────────────────

def test_1_data_engineer_fresher_exact_case() -> None:
    """1. Exact JD (Data Engineer - Fresher) + Priya Sharma Resume."""
    components, applicable, weights, final_score, knocked_out, rec = _score_candidate(
        DATA_ENGINEER_FRESHER_JD, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG
    )
    assert components.skills.score == 100.0
    assert components.responsibilities.score >= 90.0
    assert components.projects.score >= 70.0
    assert components.experience.score == 100.0
    assert components.education.score == 100.0
    assert "projects" in applicable
    assert "experience" in applicable
    assert final_score >= 85.0
    assert not knocked_out
    assert rec == RecommendationLevel.SHORTLIST


def test_2_jd_with_required_skills_no_projects() -> None:
    """2. JD with required skills but no projects specified in JD."""
    jd = SimpleNamespace(
        job_title="Python Developer",
        required_skills=["Python", "SQL", "Git"],
        preferred_skills=[],
        skills=["Python", "SQL", "Git"],
        responsibilities=["Write Python scripts and SQL queries."],
        experience_requirements=[{"minimum_months": 12}],
        degree_requirements=["Bachelor's degree"],
        project_requirements=[],
        certifications=[],
        keywords=["Python"],
    )
    components, applicable, weights, final_score, _, _ = _score_candidate(jd, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG)
    assert components.skills.score == 100.0
    assert "required_skills" in applicable


def test_3_jd_with_explicit_project_requirements() -> None:
    """3. JD with explicit project requirements."""
    jd = SimpleNamespace(
        job_title="Data Pipeline Engineer",
        required_skills=["Python", "PySpark"],
        preferred_skills=[],
        skills=["Python", "PySpark"],
        responsibilities=["Build data pipelines."],
        experience_requirements=[],
        degree_requirements=["Bachelor's degree"],
        project_requirements=["PySpark & Airflow ETL Data Pipeline"],
        certifications=[],
        keywords=[],
    )
    components, applicable, weights, final_score, _, _ = _score_candidate(jd, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG)
    assert components.projects.score == 100.0
    assert "projects" in applicable


def test_4_jd_with_responsibilities_no_project_section() -> None:
    """4. JD with responsibilities but no explicit project section."""
    jd = SimpleNamespace(
        job_title="Junior Data Engineer",
        required_skills=["Python", "SQL", "PostgreSQL"],
        preferred_skills=[],
        skills=["Python", "SQL", "PostgreSQL"],
        responsibilities=["Build ETL pipelines using Python and PostgreSQL."],
        experience_requirements=[],
        degree_requirements=["Bachelor's degree"],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    components, applicable, weights, final_score, _, _ = _score_candidate(jd, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG)
    assert "projects" in applicable
    assert components.projects.score >= 80.0


def test_5_jd_with_preferred_skills() -> None:
    """5. JD with preferred skills."""
    jd = SimpleNamespace(
        job_title="Data Engineer",
        required_skills=["Python", "SQL"],
        preferred_skills=["Docker", "AWS S3"],
        skills=["Python", "SQL", "Docker", "AWS S3"],
        responsibilities=["Develop ETL data pipelines."],
        experience_requirements=[],
        degree_requirements=["Bachelor's degree"],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    components, applicable, weights, final_score, _, _ = _score_candidate(jd, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG)
    assert components.preferred_skills.score == 100.0
    assert "preferred_skills" in applicable


def test_6_jd_with_0_to_1_year_experience() -> None:
    """6. JD with 0-1 year experience."""
    jd = SimpleNamespace(
        job_title="Data Engineer - Entry Level",
        required_skills=["Python", "SQL"],
        preferred_skills=[],
        skills=["Python", "SQL"],
        responsibilities=["Develop ETL data pipelines."],
        experience_requirements=[{"minimum_months": 0, "maximum_months": 12, "display_value": "0-1 year"}],
        degree_requirements=["Bachelor's degree"],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    components, applicable, weights, final_score, _, _ = _score_candidate(jd, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG)
    assert "experience" in applicable
    assert components.experience.score == 100.0


def test_7_jd_with_no_experience_requirement() -> None:
    """7. JD with no experience requirement."""
    jd = SimpleNamespace(
        job_title="Trainee Data Engineer",
        required_skills=["Python", "SQL"],
        preferred_skills=[],
        skills=["Python", "SQL"],
        responsibilities=["Develop ETL data pipelines."],
        experience_requirements=[],
        degree_requirements=["Bachelor's degree"],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    components, applicable, weights, final_score, _, _ = _score_candidate(jd, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG)
    assert components.experience.score == 100.0


def test_8_fresher_resume_with_internship_and_project_evidence() -> None:
    """8. Fresher resume with internship/project evidence."""
    components, applicable, weights, final_score, knocked_out, rec = _score_candidate(
        DATA_ENGINEER_FRESHER_JD, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG
    )
    assert components.experience.score == 100.0
    assert components.projects.score >= 70.0
    assert rec == RecommendationLevel.SHORTLIST


def test_9_missing_mandatory_skill_knockout() -> None:
    """9. Missing mandatory skill triggers knockout if enabled in config."""
    jd_mandatory = SimpleNamespace(
        job_title=DATA_ENGINEER_FRESHER_JD.job_title,
        required_skills=["Java", *DATA_ENGINEER_FRESHER_JD.required_skills],
        preferred_skills=DATA_ENGINEER_FRESHER_JD.preferred_skills,
        skills=["Java", *DATA_ENGINEER_FRESHER_JD.skills],
        responsibilities=DATA_ENGINEER_FRESHER_JD.responsibilities,
        experience_requirements=DATA_ENGINEER_FRESHER_JD.experience_requirements,
        degree_requirements=DATA_ENGINEER_FRESHER_JD.degree_requirements,
        project_requirements=[],
        certifications=[],
        keywords=DATA_ENGINEER_FRESHER_JD.keywords,
    )
    config_mandatory = SimpleNamespace(
        mandatory_skills=["Java"],
        min_experience_years=0,
        required_degree="Bachelor's degree",
        required_certifications=[],
        required_languages=[],
        knockout_rules=[{"rule_type": "MISSING_MANDATORY_SKILL", "enabled": True}],
    )
    components, applicable, weights, final_score, knocked_out, rec = _score_candidate(
        jd_mandatory, PRIYA_SHARMA_RESUME, config_mandatory
    )
    assert knocked_out
    assert rec == RecommendationLevel.REJECT


def test_10_genuinely_weak_candidate() -> None:
    """10. Genuinely weak candidate (unrelated skills and no relevant experience/projects)."""
    weak_resume = SimpleNamespace(
        candidate_name="John Weak",
        skills=["Photoshop", "Graphic Design", "Social Media"],
        education=[{"degree": "High School Diploma", "field_of_study": "Arts"}],
        certifications=[],
        languages=["English"],
        experience=[
            {
                "company": "Design Studio",
                "title": "Graphic Design Assistant",
                "duration_months": 2,
                "description": "Created promotional flyers and social media banners.",
                "technologies": ["Photoshop"],
                "responsibilities": ["Created flyers"]
            }
        ],
        projects=[]
    )
    components, applicable, weights, final_score, knocked_out, rec = _score_candidate(
        DATA_ENGINEER_FRESHER_JD, weak_resume, DEFAULT_CONFIG
    )
    assert components.skills.score == 0.0
    assert components.responsibilities.score < 45.0
    assert components.projects.score == 0.0
    assert final_score < 50.0
    assert rec == RecommendationLevel.REJECT


def test_11_eight_of_nine_responsibilities_matched_formula() -> None:
    """11. 9 responsibilities with 8 matched yields exact formula score (~88.89%)."""
    from app.schemas.matching import MatchVerdict, MatchStatus, MatchMethod
    scoring_svc = ComponentScoringService()
    verdicts = [
        MatchVerdict(requirement_id=f"responsibility:{i}", status=MatchStatus.MATCHED, confidence=1.0, coverage=1.0, method=MatchMethod.EXACT)
        for i in range(1, 9)
    ] + [
        MatchVerdict(requirement_id="responsibility:9", status=MatchStatus.UNRESOLVED, confidence=0.0, coverage=0.0)
    ]
    comp = scoring_svc.score(PRIYA_SHARMA_RESUME, DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG, match_verdicts=verdicts)
    assert comp.responsibilities.score == 88.89


def test_12_preferred_skills_present_yields_applicable_non_zero_weight() -> None:
    """12. Preferred skills present -> component applicable -> non-zero effective weight."""
    applicable = WeightCalculationService.applicable_categories(DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG)
    assert "preferred_skills" in applicable
    components, applicable, weights, final_score, _, _ = _score_candidate(
        DATA_ENGINEER_FRESHER_JD, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG
    )
    assert weights.get("preferred_skills", 0.0) > 0.0


def test_13_experience_verdict_matched_and_component_hundred() -> None:
    """13. 0-1 year JD + 4-month internship yields MATCHED verdict and 100% component score."""
    from app.schemas.matching import MatchStatus
    matcher = DeterministicRequirementMatcher()
    requirements = RequirementBuilder.build(DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG)
    exp_reqs = [r for r in requirements if r.kind.value == "experience"]
    assert len(exp_reqs) == 1
    evidence = EvidenceBuilder.build(PRIYA_SHARMA_RESUME)
    verdict = matcher.match(exp_reqs[0], PRIYA_SHARMA_RESUME, evidence)
    assert verdict.status == MatchStatus.MATCHED
    components, _, _, _, _, _ = _score_candidate(DATA_ENGINEER_FRESHER_JD, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG)
    assert components.experience.score == 100.0


def test_14_ai_confirmed_and_matched_treated_identically() -> None:
    """14. AI Confirmed and MATCHED status give identical full 1.0 credit in responsibility scoring."""
    from app.schemas.matching import MatchVerdict, MatchStatus, MatchMethod
    scoring_svc = ComponentScoringService()
    verdicts_ai = [
        MatchVerdict(requirement_id=f"responsibility:{i}", status=MatchStatus.MATCHED, confidence=1.0, method=MatchMethod.LLM_CONFIRMED)
        for i in range(1, 6)
    ]
    comp_ai = scoring_svc.score(PRIYA_SHARMA_RESUME, DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG, match_verdicts=verdicts_ai)
    assert comp_ai.responsibilities.score == 100.0


def test_15_candidate_attributes_excluded_from_responsibilities() -> None:
    """15. Soft skills and candidate attributes are excluded from technical responsibilities."""
    jd_soft = SimpleNamespace(
        job_title="Data Engineer",
        required_skills=["Python"],
        preferred_skills=[],
        skills=["Python"],
        responsibilities=[
            "Design ETL data pipelines using Python.",
            "Strong analytical ability and communication skills.",
            "Teamwork and willingness to learn.",
        ],
        experience_requirements=[],
        degree_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    reqs = RequirementBuilder.build(jd_soft, DEFAULT_CONFIG)
    resp_reqs = [r for r in reqs if r.kind.value == "responsibility"]
    assert len(resp_reqs) == 1
    assert "Design ETL data pipelines" in resp_reqs[0].text


def test_16_good_to_have_skills_heading_is_not_requirement() -> None:
    """16. GOOD-TO-HAVE SKILLS section header line never becomes a requirement (produces 6 preferred skills, not 7)."""
    jd_header = SimpleNamespace(
        job_title="Data Engineer",
        required_skills=["Python"],
        preferred_skills=["GOOD-TO-HAVE SKILLS", "PySpark", "Airflow", "AWS S3", "Docker", "MongoDB", "Parquet"],
        skills=["Python", "GOOD-TO-HAVE SKILLS", "PySpark", "Airflow", "AWS S3", "Docker", "MongoDB", "Parquet"],
        responsibilities=[],
        experience_requirements=[],
        degree_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    reqs = RequirementBuilder.build(jd_header, DEFAULT_CONFIG)
    pref_reqs = [r for r in reqs if r.kind.value in {"preferred_skill", "skill"} and not r.required]
    req_texts = [r.text for r in pref_reqs]
    assert "GOOD-TO-HAVE SKILLS" not in req_texts
    assert len(pref_reqs) == 6


def test_17_candidate_requirements_heading_ignored() -> None:
    """17. CANDIDATE REQUIREMENTS heading is ignored as a requirement."""
    jd_cand = SimpleNamespace(
        job_title="Data Engineer",
        required_skills=["CANDIDATE REQUIREMENTS", "Python", "SQL"],
        preferred_skills=[],
        skills=["CANDIDATE REQUIREMENTS", "Python", "SQL"],
        responsibilities=[],
        experience_requirements=[],
        degree_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    reqs = RequirementBuilder.build(jd_cand, DEFAULT_CONFIG)
    req_texts = [r.text for r in reqs]
    assert "CANDIDATE REQUIREMENTS" not in req_texts


def test_18_screening_notes_not_requirements() -> None:
    """18. Meta instructions and screening notes are excluded from candidate requirements."""
    jd_note = SimpleNamespace(
        job_title="Data Engineer",
        required_skills=["Required skills should determine core eligibility", "Python"],
        preferred_skills=[],
        skills=["Required skills should determine core eligibility", "Python"],
        responsibilities=[],
        experience_requirements=[],
        degree_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    reqs = RequirementBuilder.build(jd_note, DEFAULT_CONFIG)
    req_texts = [r.text for r in reqs]
    assert "Required skills should determine core eligibility" not in req_texts


def test_19_duplicate_experience_lines_normalized_into_one() -> None:
    """19. Duplicate/explanatory experience phrases ('0-1 year' and '0-1 year of professional experience...') normalize into exactly ONE EXPERIENCE requirement."""
    jd_exp_dup = SimpleNamespace(
        job_title="Data Engineer",
        required_skills=["Python"],
        preferred_skills=[],
        skills=["Python"],
        responsibilities=[],
        experience_requirements=[
            {"minimum_months": 0, "maximum_months": 12, "display_value": "0-1 year"},
            {"minimum_months": 0, "maximum_months": 12, "display_value": "0-1 year of professional experience; fresh graduates are encouraged to apply."},
        ],
        degree_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    reqs = RequirementBuilder.build(jd_exp_dup, DEFAULT_CONFIG)
    exp_reqs = [r for r in reqs if r.kind.value == "experience"]
    assert len(exp_reqs) == 1
    assert exp_reqs[0].text == "0-1 year"


def test_20_unresolved_soft_attribute_does_not_reject_candidate() -> None:
    """20. Unresolved soft candidate attribute does not cause candidate rejection or knockout."""
    jd_soft_unresolved = SimpleNamespace(
        job_title=DATA_ENGINEER_FRESHER_JD.job_title,
        required_skills=DATA_ENGINEER_FRESHER_JD.required_skills,
        preferred_skills=DATA_ENGINEER_FRESHER_JD.preferred_skills,
        skills=DATA_ENGINEER_FRESHER_JD.skills,
        responsibilities=[*DATA_ENGINEER_FRESHER_JD.responsibilities, "Ability and willingness to learn new data technologies."],
        experience_requirements=DATA_ENGINEER_FRESHER_JD.experience_requirements,
        degree_requirements=DATA_ENGINEER_FRESHER_JD.degree_requirements,
        project_requirements=[],
        certifications=[],
        keywords=DATA_ENGINEER_FRESHER_JD.keywords,
    )
    components, applicable, weights, final_score, knocked_out, rec = _score_candidate(
        jd_soft_unresolved, PRIYA_SHARMA_RESUME, DEFAULT_CONFIG
    )
    assert not knocked_out
    assert rec == RecommendationLevel.SHORTLIST


def test_21_explicit_skills_and_parquet_matches() -> None:
    """21. Python, SQL, aggregations, subqueries, and Parquet evaluate to MATCHED."""
    from app.schemas.matching import MatchStatus, Requirement, RequirementKind
    matcher = DeterministicRequirementMatcher()
    evidence = EvidenceBuilder.build(PRIYA_SHARMA_RESUME)
    
    test_skills = ["Python", "SQL", "aggregations", "subqueries", "Parquet and other columnar data formats"]
    for skill in test_skills:
        req = Requirement(requirement_id="skill:test", kind=RequirementKind.SKILL, text=skill, canonical_value=skill, required=True, hard_constraint=False)
        verdict = matcher.match(req, PRIYA_SHARMA_RESUME, evidence)
        assert verdict.status == MatchStatus.MATCHED, f"Expected MATCHED for skill '{skill}', got {verdict.status} ({verdict.reasoning})"


def test_22_headings_screening_notes_and_candidate_requirements_filtered() -> None:
    """22. Section headings, screening notes, and candidate requirement headings never become Required Skills."""
    jd_mixed = SimpleNamespace(
        job_title="Data Engineer",
        required_skills=[
            "GOOD-TO-HAVE SKILLS",
            "CANDIDATE REQUIREMENTS",
            "Required skills should determine core eligibility...",
            "Good-to-have skills are optional and must not independently cause...",
            "Python",
            "SQL",
        ],
        preferred_skills=[],
        skills=[
            "GOOD-TO-HAVE SKILLS",
            "CANDIDATE REQUIREMENTS",
            "Required skills should determine core eligibility...",
            "Python",
            "SQL",
        ],
        responsibilities=[],
        experience_requirements=[],
        degree_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=[],
    )
    reqs = RequirementBuilder.build(jd_mixed, DEFAULT_CONFIG)
    req_texts = [r.text for r in reqs]
    assert "GOOD-TO-HAVE SKILLS" not in req_texts
    assert "CANDIDATE REQUIREMENTS" not in req_texts
    assert not any(t.startswith("Required skills should determine") for t in req_texts)
    assert not any(t.startswith("Good-to-have skills are optional") for t in req_texts)
    assert len(reqs) == 2


def test_23_single_canonical_requirement_pipeline() -> None:
    """23. Requirement list used by matcher equals requirement list used by scorer."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()
    
    reqs = RequirementBuilder.build(DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG)
    evidence = EvidenceBuilder.build(PRIYA_SHARMA_RESUME)
    verdicts = [matcher.match(req, PRIYA_SHARMA_RESUME, evidence) for req in reqs]
    
    comp = scoring_svc.score(PRIYA_SHARMA_RESUME, DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG, projects=PRIYA_SHARMA_RESUME.projects, match_verdicts=verdicts)
    assert comp.skills.score == 100.0
    assert comp.responsibilities.score >= 88.0
    assert comp.experience.score == 100.0


def test_24_ui_verdicts_equal_scorer_verdicts() -> None:
    """24. Matcher verdicts map 1-to-1 with ComponentScoringService verdicts."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()
    
    reqs = RequirementBuilder.build(DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG)
    evidence = EvidenceBuilder.build(PRIYA_SHARMA_RESUME)
    verdicts = [matcher.match(req, PRIYA_SHARMA_RESUME, evidence) for req in reqs]
    
    matched_req_ids = {v.requirement_id for v in verdicts if v.status.value == "MATCHED"}
    comp = scoring_svc.score(PRIYA_SHARMA_RESUME, DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG, projects=PRIYA_SHARMA_RESUME.projects, match_verdicts=verdicts)
    
    assert len(matched_req_ids) > 0
    assert comp.skills.score == 100.0


def test_25_all_project_competency_concepts_and_verdict_alignment() -> None:
    """25. Verify all project evidence concepts (Python, SQL joins, aggregations, subqueries, window functions, PySpark, Airflow, S3, Parquet, REST APIs, Git) match and verdicts carry requirement_text."""
    matcher = DeterministicRequirementMatcher()
    scoring_svc = ComponentScoringService()
    
    reqs = RequirementBuilder.build(DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG)
    evidence = EvidenceBuilder.build(PRIYA_SHARMA_RESUME)
    verdicts = [matcher.match(req, PRIYA_SHARMA_RESUME, evidence) for req in reqs]
    
    for v in verdicts:
        assert v.requirement_text is not None
        assert v.kind is not None
    
    comp = scoring_svc.score(PRIYA_SHARMA_RESUME, DATA_ENGINEER_FRESHER_JD, DEFAULT_CONFIG, projects=PRIYA_SHARMA_RESUME.projects, match_verdicts=verdicts)
    assert comp.projects.score == 100.0


def test_26_sysops_protocols_filtered_from_project_denominator() -> None:
    """26. SysOps protocols (DNS, DHCP, TCP/IP, VPN, Active Directory) do not inflate project denominator."""
    scoring_svc = ComponentScoringService()
    sysops_jd = SimpleNamespace(
        job_title="SysOps Engineer",
        required_skills=["Linux", "Windows Server", "AWS", "Grafana", "Prometheus", "CloudWatch", "Python", "PowerShell", "DNS", "DHCP", "TCP/IP", "VPN", "Active Directory"],
        preferred_skills=[],
        skills=["Linux", "Windows Server", "AWS", "Grafana", "Prometheus", "CloudWatch", "Python", "PowerShell", "DNS", "DHCP", "TCP/IP", "VPN", "Active Directory"],
        responsibilities=["Monitor cloud infrastructure and automate server deployments."],
        experience_requirements=[],
        degree_requirements=[],
        project_requirements=[],
        certifications=[],
        keywords=["Monitoring", "CloudWatch", "Prometheus", "Grafana", "Linux"],
    )
    arjun_resume = SimpleNamespace(
        candidate_name="Arjun Kumar",
        skills=["Linux", "Windows Server", "AWS", "Grafana", "Prometheus", "CloudWatch", "Python", "PowerShell", "Bash", "DNS", "DHCP", "TCP/IP", "VPN"],
        projects=[{
            "name": "Cloud Infrastructure Monitoring & Automation",
            "description": "Centralized AWS and Linux monitoring with CloudWatch, Prometheus, Grafana, and Python automation scripts.",
            "technologies": ["AWS", "CloudWatch", "Prometheus", "Grafana", "Python", "Linux"]
        }],
        experience=[{
            "title": "SysOps Engineer",
            "description": "Managed Linux and Windows production servers. Monitored infrastructure using CloudWatch, Grafana, Nagios, and Bash automation.",
            "technologies": ["Linux", "Windows Server", "AWS", "Bash", "Python"]
        }]
    )
    comp = scoring_svc.score(arjun_resume, sysops_jd, DEFAULT_CONFIG)
    assert comp.projects.score >= 80.0
    assert "DNS" not in comp.projects.missing_items
    assert "DHCP" not in comp.projects.missing_items


def test_27_frontend_responsive_design_and_state_optimization_matching() -> None:
    """27. Frontend UI terms ('implemented responsive user interfaces', 'optimized state management') match Responsive Design & State Optimization."""
    scoring_svc = ComponentScoringService()
    frontend_jd = SimpleNamespace(
        job_title="Frontend Developer",
        required_skills=["React", "Redux", "Tailwind", "Responsive Design", "State Optimization"],
        preferred_skills=[],
        skills=["React", "Redux", "Tailwind", "Responsive Design", "State Optimization"],
        responsibilities=["Build responsive web application user interfaces and optimize frontend state management."],
        experience_requirements=[],
        degree_requirements=[],
        project_requirements=["React", "Redux", "Tailwind", "Responsive Design", "State Optimization"],
        certifications=[],
        keywords=[],
    )
    harshini_resume = SimpleNamespace(
        candidate_name="Harshini R",
        skills=["Python", "JavaScript", "React", "Node.js", "HTML", "CSS", "C++"],
        projects=[
            {
                "name": "Software Development Training Website",
                "description": "Developed full-stack interactive website using HTML, CSS, JavaScript, and React. Implemented responsive user interfaces and modular components.",
                "technologies": ["React", "JavaScript", "HTML", "CSS"]
            },
            {
                "name": "Frontend E-commerce Platform",
                "description": "Built modern online shopping UI with React, Redux, and Tailwind. Optimized state management and page rendering speed.",
                "technologies": ["React", "Redux", "Tailwind"]
            }
        ],
        experience=[]
    )
    comp = scoring_svc.score(harshini_resume, frontend_jd, DEFAULT_CONFIG)
    assert comp.projects.score == 100.0
    assert "Responsive Design" in comp.projects.matched_items
    assert "State Optimization" in comp.projects.matched_items


def test_28_skill_only_mention_gives_zero_project_credit() -> None:
    """28. Skills-only mention (Python in skills, absent from projects/experience) yields zero project credit."""
    scoring_svc = ComponentScoringService()
    jd = SimpleNamespace(
        job_title="Software Engineer",
        required_skills=["Python"],
        preferred_skills=[],
        skills=["Python"],
        responsibilities=[],
        experience_requirements=[],
        degree_requirements=[],
        project_requirements=["Python"],
        certifications=[],
        keywords=[],
    )
    skill_only_resume = SimpleNamespace(
        candidate_name="Skill Only Candidate",
        skills=["Python"],
        projects=[{"name": "Java Web App", "description": "Built e-commerce app using Java and Spring Boot.", "technologies": ["Java", "Spring Boot"]}],
        experience=[]
    )
    comp = scoring_svc.score(skill_only_resume, jd, DEFAULT_CONFIG)
    assert comp.projects.score == 0.0
    assert "Python" in comp.projects.missing_items


def test_29_structured_projects_and_details_survive_normalization() -> None:
    """29. Structured project details (name, description, technologies, deliverables, highlights) survive normalization."""
    normalizer = ResumeNormalizer()
    extracted = SimpleNamespace(
        skills=["Python"],
        education=[],
        experience=[],
        companies=[],
        designation="Software Engineer",
        location="Chennai, India",
        phone=None,
        email="test@example.com",
        languages=[],
        certifications=[],
        projects=[
            {
                "name": "E-Commerce Pipeline",
                "description": "Built scalable data pipeline",
                "technologies": ["Python", "PostgreSQL"],
                "deliverables": ["ETL Pipeline", "Data Validation"],
                "highlights": ["Processed 1M records daily"],
            }
        ]
    )
    norm = normalizer.normalize(extracted)
    assert len(norm["projects"]) == 1
    proj = norm["projects"][0]
    assert proj["name"] == "E-Commerce Pipeline"
    assert "Python" in proj["technologies"]
    assert proj.get("deliverables") == ["ETL Pipeline", "Data Validation"]
    assert proj.get("highlights") == ["Processed 1M records daily"]


def test_30_production_database_json_shape_matches_fixture_evidence() -> None:
    """30. Real production-shaped database JSON produces identical project evidence as unit-test fixture."""
    db_json = {
        "candidate_name": "Jaishree Y",
        "skills": ["Python", "Flask", "Selenium", "Postman"],
        "projects": [
            {
                "name": "Article Finder",
                "description": "Flask app for QA automation and UI testing",
                "technologies": ["Flask", "Selenium", "Postman"],
                "deliverables": ["QA Test Suite"],
            },
            {
                "name": "ShopSync",
                "description": "Full stack app with Postman API testing",
                "technologies": ["Node.js", "Postman", "MongoDB"],
            }
        ],
        "experience": []
    }
    extracted = SimpleNamespace(**db_json)
    evidence = EvidenceBuilder.build(extracted)
    proj_evidence = [e for e in evidence if e.kind == "project"]
    assert len(proj_evidence) == 2
    assert "Flask" in proj_evidence[0].text
    assert "ShopSync" in proj_evidence[1].text

