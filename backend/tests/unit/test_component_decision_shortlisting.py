from types import SimpleNamespace

from app.schemas.scoring import RecommendationLevel
from app.services.scoring.recommendation_service import RecommendationService, SHORTLIST_COMPONENT_THRESHOLD
from app.services.scoring.weight_calculation_service import COMPONENT_WEIGHTS


def make_components(
    skills: float = 0.0,
    responsibilities: float = 0.0,
    projects: float = 0.0,
    preferred_skills: float = 0.0,
    certifications: float = 0.0,
    education: float = 0.0,
    pref_weight: float = 15.0,
    cert_weight: float = 5.0,
    edu_weight: float = 0.0,
):
    return SimpleNamespace(
        skills=SimpleNamespace(score=skills, weight=30.0),
        responsibilities=SimpleNamespace(score=responsibilities, weight=25.0),
        projects=SimpleNamespace(score=projects, weight=25.0),
        preferred_skills=SimpleNamespace(score=preferred_skills, weight=pref_weight),
        certifications=SimpleNamespace(score=certifications, weight=cert_weight),
        education=SimpleNamespace(score=education, weight=edu_weight),
    )


def test_1_required_skills_triggers_shortlist():
    """TEST 1 — Required Skills = 50%, Responsibilities = 20%, Projects = 20%, Preferred Skills = 0% -> SHORTLIST."""
    comp = make_components(skills=50.0, responsibilities=20.0, projects=20.0, preferred_skills=0.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.SHORTLIST
    assert "SHORTLIST" in reason
    assert "Required Skills" in reason


def test_2_required_skills_below_threshold():
    """TEST 2 — Required Skills = 49%, Responsibilities = 40%, Projects = 40% -> REVIEW."""
    comp = make_components(skills=49.0, responsibilities=40.0, projects=40.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.REVIEW
    assert "REVIEW" in reason


def test_3_responsibilities_triggers_shortlist():
    """TEST 3 — Required Skills = 30%, Responsibilities = 50%, Projects = 20% -> SHORTLIST."""
    comp = make_components(skills=30.0, responsibilities=50.0, projects=20.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.SHORTLIST
    assert "Responsibilities" in reason


def test_4_projects_triggers_shortlist():
    """TEST 4 — Required Skills = 20%, Responsibilities = 30%, Projects = 50% -> SHORTLIST."""
    comp = make_components(skills=20.0, responsibilities=30.0, projects=50.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.SHORTLIST
    assert "Projects" in reason


def test_5_preferred_skills_alone_does_not_shortlist():
    """TEST 5 — Required Skills = 20%, Responsibilities = 10%, Projects = 15%, Preferred Skills = 80% -> NOT SHORTLIST (REVIEW or REJECT)."""
    comp = make_components(skills=20.0, responsibilities=10.0, projects=15.0, preferred_skills=80.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level != RecommendationLevel.SHORTLIST
    assert level in (RecommendationLevel.REVIEW, RecommendationLevel.REJECT)


def test_6_no_meaningful_evidence():
    """TEST 6 — Required Skills = 15%, Responsibilities = 10%, Projects = 5%, Preferred Skills = 0%, Certifications = 0%, Education = 0% -> REJECT."""
    comp = make_components(skills=15.0, responsibilities=10.0, projects=5.0, preferred_skills=0.0, certifications=0.0, education=0.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.REJECT
    assert "REJECT" in reason


def test_7_critical_knockout_precedence():
    """TEST 7 — Critical Knockout fails -> REJECT regardless of high component scores."""
    comp = make_components(skills=80.0, responsibilities=70.0, projects=70.0)
    level, reason = RecommendationService.evaluate(comp, is_knocked_out=True, knockout_reason="Missing mandatory Python requirement")
    assert level == RecommendationLevel.REJECT
    assert "mandatory requirement" in reason


def test_8_exactly_50_percent_inclusive():
    """TEST 8 — Required Skills = 50% (inclusive) with additional evidence -> SHORTLIST."""
    comp = make_components(skills=50.0, responsibilities=10.0, projects=10.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.SHORTLIST
    assert SHORTLIST_COMPONENT_THRESHOLD == 50.0


def test_9_just_below_50_percent():
    """TEST 9 — Required Skills = 49.99%, Responsibilities = 40%, Projects = 40% -> NOT SHORTLIST (REVIEW)."""
    comp = make_components(skills=49.99, responsibilities=40.0, projects=40.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.REVIEW


def test_10_no_overall_score_dependency():
    """TEST 10 — Verify recommendation logic does not call or depend on final_score or overall_score."""
    comp = make_components(skills=60.0, responsibilities=30.0, projects=30.0)
    level = RecommendationService.recommend(final_score=0.0, components=comp)
    assert level == RecommendationLevel.SHORTLIST


def test_11_weights_remain_unchanged():
    """TEST 11 — Confirm base component weights sum to 100.0% and match exact percentages."""
    expected = {
        "required_skills": 45.0,
        "responsibilities": 40.0,
        "preferred_skills": 15.0,
        "certifications": 0.0,
        "experience": 0.0,
        "education": 0.0,
        "languages": 0.0,
        "projects": 0.0,
    }
    assert COMPONENT_WEIGHTS == expected
    assert sum(COMPONENT_WEIGHTS.values()) == 100.0


# ── ZERO-WEIGHT & INACTIVE COMPONENT REGRESSION TESTS ──

def test_regression_a_exact_bug_from_production_ui():
    """Test A — Exact bug from UI: Req Skills=45%, Resp=44%, Proj=45%, Pref Skills=100% (Weight=0%), Certs=100% (Weight=0%) -> REVIEW."""
    comp = make_components(
        skills=45.0,
        responsibilities=44.0,
        projects=45.0,
        preferred_skills=100.0,
        certifications=100.0,
        pref_weight=0.0,
        cert_weight=0.0,
    )
    eff_weights = {"required_skills": 37.5, "responsibilities": 31.25, "projects": 31.25, "preferred_skills": 0.0, "certifications": 0.0, "education": 0.0, "experience": 0.0}
    level, reason = RecommendationService.evaluate(comp, effective_weights=eff_weights)
    assert level == RecommendationLevel.REVIEW
    assert level != RecommendationLevel.SHORTLIST


def test_regression_b_zero_weight_preferred_skills_cannot_rescue():
    """Test B — Req Skills=49%, Resp=49%, Proj=49%, Pref Skills=100% (Weight=0%) -> REVIEW."""
    comp = make_components(skills=49.0, responsibilities=49.0, projects=49.0, preferred_skills=100.0, pref_weight=0.0)
    eff_weights = {"required_skills": 37.5, "responsibilities": 31.25, "projects": 31.25, "preferred_skills": 0.0, "certifications": 0.0, "education": 0.0, "experience": 0.0}
    level, reason = RecommendationService.evaluate(comp, effective_weights=eff_weights)
    assert level == RecommendationLevel.REVIEW


def test_regression_c_zero_weight_certification_cannot_rescue():
    """Test C — Req Skills=49%, Resp=49%, Proj=49%, Certifications=100% (Weight=0%) -> REVIEW."""
    comp = make_components(skills=49.0, responsibilities=49.0, projects=49.0, certifications=100.0, cert_weight=0.0)
    eff_weights = {"required_skills": 37.5, "responsibilities": 31.25, "projects": 31.25, "preferred_skills": 0.0, "certifications": 0.0, "education": 0.0, "experience": 0.0}
    level, reason = RecommendationService.evaluate(comp, effective_weights=eff_weights)
    assert level == RecommendationLevel.REVIEW


def test_regression_d_zero_weight_education_cannot_rescue():
    """Test D — Req Skills=49%, Resp=49%, Proj=49%, Education=100% (Weight=0%) -> REVIEW."""
    comp = make_components(skills=49.0, responsibilities=49.0, projects=49.0, education=100.0, edu_weight=0.0)
    eff_weights = {"required_skills": 37.5, "responsibilities": 31.25, "projects": 31.25, "preferred_skills": 0.0, "certifications": 0.0, "education": 0.0, "experience": 0.0}
    level, reason = RecommendationService.evaluate(comp, effective_weights=eff_weights)
    assert level == RecommendationLevel.REVIEW


def test_regression_e_zero_weight_experience_cannot_rescue():
    """Test E — Req Skills=49%, Resp=49%, Proj=49%, Experience weight=0% -> REVIEW."""
    comp = make_components(skills=49.0, responsibilities=49.0, projects=49.0)
    eff_weights = {"required_skills": 37.5, "responsibilities": 31.25, "projects": 31.25, "preferred_skills": 0.0, "certifications": 0.0, "education": 0.0, "experience": 0.0}
    level, reason = RecommendationService.evaluate(comp, effective_weights=eff_weights)
    assert level == RecommendationLevel.REVIEW


def test_regression_f_required_skills_50_with_no_additional_active_component():
    """Test F — Req Skills=50%, Resp=0%, Proj=0%, Pref Skills=100% (Weight=0%) -> REVIEW (No additional ACTIVE component)."""
    comp = make_components(skills=50.0, responsibilities=0.0, projects=0.0, preferred_skills=100.0, pref_weight=0.0, cert_weight=0.0)
    eff_weights = {"required_skills": 37.5, "responsibilities": 31.25, "projects": 31.25, "preferred_skills": 0.0, "certifications": 0.0, "education": 0.0, "experience": 0.0}
    level, reason = RecommendationService.evaluate(comp, effective_weights=eff_weights)
    assert level == RecommendationLevel.REVIEW
    assert level != RecommendationLevel.SHORTLIST


def test_regression_g_active_additional_component_works():
    """Test G — Req Skills=50%, Resp=40% (Active, Weight>0) -> SHORTLIST."""
    comp = make_components(skills=50.0, responsibilities=40.0, projects=0.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.SHORTLIST


def test_regression_h_active_preferred_skills_works():
    """Test H — Req Skills=55%, Resp=10%, Pref Skills=30% (Weight=15%>0%) -> SHORTLIST."""
    comp = make_components(skills=55.0, responsibilities=10.0, projects=0.0, preferred_skills=30.0, pref_weight=15.0)
    level, reason = RecommendationService.evaluate(comp)
    assert level == RecommendationLevel.SHORTLIST
