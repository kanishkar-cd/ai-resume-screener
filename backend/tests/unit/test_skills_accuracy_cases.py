import pytest
from types import SimpleNamespace
from app.services.matching_service import HybridMatchingService
from app.schemas.matching import MatchStatus, MatchMethod, RequirementKind
from app.core.config import Settings


def make_settings():
    return Settings(
        GROQ_API_KEY="",  # Proves 0 Groq calls for skills
        CEREBRAS_API_KEY="",
        ENABLE_HYBRID_MATCHING=False,
    )


async def execute_skill_match(name, job_skills, resume_skills, exp_desc="", proj_desc="", summary=""):
    hybrid = HybridMatchingService(settings=make_settings())
    fake_job = SimpleNamespace(
        required_skills=job_skills,
        skills=job_skills,
        responsibilities=[],
    )
    fake_resume = SimpleNamespace(
        id=name,
        skills=resume_skills,
        experience=[{"title": "Software Engineer", "description": exp_desc}] if exp_desc else [],
        projects=[{"name": "Core Project", "description": proj_desc}] if proj_desc else [],
        education=[],
        certifications=[],
    )
    fake_extracted = SimpleNamespace(
        skills=resume_skills,
        experience=[{"title": "Software Engineer", "description": exp_desc}] if exp_desc else [],
        projects=[{"name": "Core Project", "description": proj_desc}] if proj_desc else [],
        education=[],
        certifications=[],
        languages=[],
        summary=summary,
    )

    _, verdicts = await hybrid.match(fake_job, fake_resume, fake_extracted)
    return verdicts


@pytest.mark.asyncio
async def test_case_1_exact_skill_match():
    """Case 1: Exact skill match -> MATCHED, full points (1.0)."""
    verdicts = await execute_skill_match("exact", ["Python"], ["Python"])
    assert len(verdicts) == 1
    v = verdicts[0]
    assert v.status == MatchStatus.MATCHED
    assert v.coverage == 1.0
    assert v.method in {MatchMethod.EXACT, MatchMethod.ALIAS}
    assert len(v.evidence_ids) > 0


@pytest.mark.asyncio
async def test_case_2_known_canonical_alias_synonym():
    """Case 2: Known canonical alias/synonym -> MATCHED, full points (1.0)."""
    # Kubernetes -> K8s
    v_k8s = await execute_skill_match("alias_k8s", ["Kubernetes"], ["K8s"])
    assert v_k8s[0].status == MatchStatus.MATCHED
    assert v_k8s[0].coverage == 1.0
    assert len(v_k8s[0].evidence_ids) > 0

    # PostgreSQL -> Postgres
    v_pg = await execute_skill_match("alias_pg", ["PostgreSQL"], ["Postgres"])
    assert v_pg[0].status == MatchStatus.MATCHED
    assert v_pg[0].coverage == 1.0
    assert len(v_pg[0].evidence_ids) > 0

    # JavaScript -> JS
    v_js = await execute_skill_match("alias_js", ["JavaScript"], ["JS"])
    assert v_js[0].status == MatchStatus.MATCHED
    assert v_js[0].coverage == 1.0
    assert len(v_js[0].evidence_ids) > 0


@pytest.mark.asyncio
async def test_case_3_conjunction_compound_skills():
    """Case 3: Conjunction/compound skill -> recognize valid combinations & give appropriate credit."""
    # Full conjunction: Python and Docker with both present
    v_full = await execute_skill_match("conj_full", ["Python and Docker"], ["Python", "Docker"])
    assert v_full[0].status == MatchStatus.MATCHED
    assert v_full[0].coverage == 1.0

    # Partial conjunction: Python and Docker with only Python present
    v_part = await execute_skill_match("conj_part", ["Python and Docker"], ["Python"])
    assert v_part[0].status == MatchStatus.PARTIALLY_MATCHED
    assert v_part[0].coverage == 0.5

    # Disjunction: MongoDB or PostgreSQL with one present
    v_disj = await execute_skill_match("disj", ["MongoDB or PostgreSQL"], ["MongoDB"])
    assert v_disj[0].status == MatchStatus.MATCHED
    assert v_disj[0].coverage == 1.0


@pytest.mark.asyncio
async def test_case_4_related_semantic_skills():
    """Case 4: Related/semantic skill -> MATCHED or PARTIALLY_MATCHED based on evidence strength."""
    # Relational Databases -> PostgreSQL
    v_rel_db = await execute_skill_match("rel_db", ["Relational Databases"], ["PostgreSQL"])
    assert v_rel_db[0].status == MatchStatus.MATCHED
    assert v_rel_db[0].coverage == 1.0
    assert len(v_rel_db[0].evidence_ids) > 0

    # Kafka -> Message Queues / Event Streaming
    v_mq = await execute_skill_match("rel_mq", ["Kafka"], [], exp_desc="Architected distributed event streaming using message queues")
    assert v_mq[0].status in {MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED}
    assert v_mq[0].coverage >= 0.5
    assert len(v_mq[0].evidence_ids) > 0

    # Containerization -> Docker
    v_cont = await execute_skill_match("rel_cont", ["Containerization"], ["Docker"])
    assert v_cont[0].status in {MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED}
    assert v_cont[0].coverage >= 0.5


@pytest.mark.asyncio
async def test_case_5_genuine_partial_skill():
    """Case 5: Genuine partial skill -> PARTIALLY_MATCHED with existing partial coverage/points."""
    # Compound skill missing one part
    v_compound = await execute_skill_match("partial_compound", ["React and GraphQL"], ["React"])
    assert v_compound[0].status == MatchStatus.PARTIALLY_MATCHED
    assert v_compound[0].coverage == 0.5
    assert 0.0 < v_compound[0].coverage < 1.0


@pytest.mark.asyncio
async def test_case_6_completely_unrelated_skill():
    """Case 6: Completely unrelated skill -> NO_MATCH, exactly 0 points."""
    v_unrelated = await execute_skill_match("unrelated", ["Kubernetes"], ["Photoshop", "Graphic Design", "Typography"])
    assert v_unrelated[0].status == MatchStatus.NO_MATCH
    assert v_unrelated[0].coverage == 0.0
    assert v_unrelated[0].evidence_ids == []


@pytest.mark.asyncio
async def test_case_7_generic_word_false_positive():
    """
    Case 7: Generic-word false positive ->
    'Rust programming' must NOT match 'Java programming' simply because both contain 'programming'.
    Words such as developer, programming, concepts, technology, etc. must not independently create a skill match.
    """
    v_generic = await execute_skill_match(
        "generic_fp",
        ["Rust programming"],
        ["Java programming"],
        summary="Experienced Java developer with strong programming fundamentals and technology background",
    )
    assert v_generic[0].status == MatchStatus.NO_MATCH
    assert v_generic[0].coverage == 0.0
    assert v_generic[0].evidence_ids == []

    # C++ concepts vs Python concepts
    v_generic2 = await execute_skill_match(
        "generic_fp2",
        ["C++ concepts"],
        ["Python developer"],
        summary="Fullstack software development with core engineering concepts",
    )
    assert v_generic2[0].status == MatchStatus.NO_MATCH
    assert v_generic2[0].coverage == 0.0
    assert v_generic2[0].evidence_ids == []


@pytest.mark.asyncio
async def test_case_8_evidence_relevance():
    """Case 8: Evidence relevance -> Project/experience evidence receives credit only when genuinely demonstrating skill."""
    # Good evidence in project: Docker explicitly demonstrated
    v_good = await execute_skill_match(
        "ev_good",
        ["Docker"],
        [],
        proj_desc="Containerized backend microservices using Docker and orchestrated multi-container setups",
    )
    assert v_good[0].status in {MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED}
    assert v_good[0].coverage >= 0.5
    assert len(v_good[0].evidence_ids) > 0

    # Irrelevant project: Art project with Photoshop should NOT match Docker
    v_bad = await execute_skill_match(
        "ev_bad",
        ["Docker"],
        [],
        proj_desc="Designed digital banner advertisements and marketing collateral using Adobe Creative Suite",
    )
    assert v_bad[0].status == MatchStatus.NO_MATCH
    assert v_bad[0].coverage == 0.0
    assert v_bad[0].evidence_ids == []


@pytest.mark.asyncio
async def test_case_9_evidence_ids_preserved():
    """Case 9: Deterministic matches preserve valid evidence IDs."""
    v = await execute_skill_match(
        "ev_ids",
        ["Python", "PostgreSQL"],
        ["Python"],
        exp_desc="Managed relational databases using PostgreSQL schemas",
    )
    assert len(v) == 2
    for item in v:
        if item.status in {MatchStatus.MATCHED, MatchStatus.PARTIALLY_MATCHED}:
            assert len(item.evidence_ids) > 0
            assert all(isinstance(eid, str) and (eid.startswith("skills:") or eid.startswith("experience:") or eid.startswith("project:")) for eid in item.evidence_ids)


@pytest.mark.asyncio
async def test_multi_resume_deliberately_different_profiles():
    """
    Multi-resume validation with 4 deliberately different resumes:
    1. Strong skills match
    2. Strong + related/semantic skills
    3. Partial skills match
    4. Weak/almost no skills match
    
    Verifies:
    - Meaningfully different Skills scores reflecting actual evidence.
    - 0 Groq calls for all Required Skills.
    - 0 EVALUATION_FAILED.
    - Independent skill verdicts.
    """
    job_skills = ["Python", "Docker", "PostgreSQL", "Kubernetes", "Redis"]

    # 1. Strong Match: Has all 5 exact/canonical skills
    resume_strong = SimpleNamespace(
        id="strong_candidate",
        skills=["Python", "Docker", "PostgreSQL", "Kubernetes", "Redis"],
        experience=[{"title": "Senior Backend Engineer", "description": "Built microservices in Python with Docker and K8s"}],
        projects=[],
        education=[],
        certifications=[],
    )
    extracted_strong = SimpleNamespace(
        skills=["Python", "Docker", "PostgreSQL", "Kubernetes", "Redis"],
        experience=[{"title": "Senior Backend Engineer", "description": "Built microservices in Python with Docker and K8s"}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
        summary="Senior backend developer with Python, Docker, Postgres, K8s, Redis",
    )

    # 2. Strong + Related/Semantic Match: Has Python, Docker, relational db (MySQL), container orchestration, caching (Memcached)
    resume_related = SimpleNamespace(
        id="related_candidate",
        skills=["Python", "Docker", "MySQL"],
        experience=[{"title": "Cloud Engineer", "description": "Managed container orchestration and in-memory key-value cache clusters"}],
        projects=[],
        education=[],
        certifications=[],
    )
    extracted_related = SimpleNamespace(
        skills=["Python", "Docker", "MySQL"],
        experience=[{"title": "Cloud Engineer", "description": "Managed container orchestration and in-memory key-value cache clusters"}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
        summary="Cloud Engineer with Python and containerization experience",
    )

    # 3. Partial Match: Has Python and partial Docker experience only, missing Postgres, K8s, Redis
    resume_partial = SimpleNamespace(
        id="partial_candidate",
        skills=["Python"],
        experience=[{"title": "Junior Developer", "description": "Used Docker containers locally for development"}],
        projects=[],
        education=[],
        certifications=[],
    )
    extracted_partial = SimpleNamespace(
        skills=["Python"],
        experience=[{"title": "Junior Developer", "description": "Used Docker containers locally for development"}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
        summary="Junior Python developer",
    )

    # 4. Weak / Almost No Skills Match: Graphic Designer with UI design tools
    resume_weak = SimpleNamespace(
        id="weak_candidate",
        skills=["Photoshop", "Illustrator", "Figma", "Typography"],
        experience=[{"title": "Graphic Designer", "description": "Designed marketing assets and web UI mockups"}],
        projects=[],
        education=[],
        certifications=[],
    )
    extracted_weak = SimpleNamespace(
        skills=["Photoshop", "Illustrator", "Figma", "Typography"],
        experience=[{"title": "Graphic Designer", "description": "Designed marketing assets and web UI mockups"}],
        projects=[],
        education=[],
        certifications=[],
        languages=[],
        summary="Creative visual designer with branding expertise",
    )

    fake_job = SimpleNamespace(
        required_skills=job_skills,
        skills=job_skills,
        responsibilities=[],
    )

    hybrid = HybridMatchingService(settings=make_settings())

    _, v_strong = await hybrid.match(fake_job, resume_strong, extracted_strong)
    _, v_related = await hybrid.match(fake_job, resume_related, extracted_related)
    _, v_partial = await hybrid.match(fake_job, resume_partial, extracted_partial)
    _, v_weak = await hybrid.match(fake_job, resume_weak, extracted_weak)

    # Calculate skills score for each resume (sum of coverage_score / total required skills * 100)
    def calc_skill_score(verdicts):
        total_cov = sum(float(getattr(v, "coverage_score", 0.0) or 0.0) for v in verdicts)
        return round((total_cov / len(verdicts)) * 100.0, 1)

    score_strong = calc_skill_score(v_strong)
    score_related = calc_skill_score(v_related)
    score_partial = calc_skill_score(v_partial)
    score_weak = calc_skill_score(v_weak)

    print(f"\nSkills Scores: Strong={score_strong}%, Related={score_related}%, Partial={score_partial}%, Weak={score_weak}%")

    # Strict ordering and meaningful differentiation
    assert score_strong == 100.0, f"Strong profile should be 100%, got {score_strong}"
    assert score_related >= 60.0, f"Related profile should have substantial credit (>=60%), got {score_related}"
    assert score_partial >= 30.0 and score_partial <= 50.0, f"Partial profile should be 30-50%, got {score_partial}"
    assert score_weak == 0.0, f"Weak profile should be 0.0%, got {score_weak}"

    assert score_strong > score_related > score_partial > score_weak

    # Verify no EVALUATION_FAILED
    for all_v in [v_strong, v_related, v_partial, v_weak]:
        assert not any(v.status == MatchStatus.EVALUATION_FAILED for v in all_v)
