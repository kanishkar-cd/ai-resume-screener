import pytest
from app.services.extractors.job_extractor import JobDescriptionExtractor
from app.services.jd_extraction_service import _extract_education, clean_education_phrase
from app.services.jd_normalization_service import _canonicalize_degree


def test_clean_education_phrase_strips_generic_trailers() -> None:
    assert clean_education_phrase("Bachelor of Technology in Artificial Intelligence and Data Science or related field.") == "Bachelor of Technology in Artificial Intelligence and Data Science"
    assert clean_education_phrase("Master of Science in Electrical Engineering or equivalent discipline") == "Master of Science in Electrical Engineering"
    assert clean_education_phrase("B.E. in Electronics and Communication Engineering or relevant degree") == "B.E. in Electronics and Communication Engineering"
    assert clean_education_phrase("Ph.D in Machine Learning or related experience.") == "Ph.D in Machine Learning"


def test_extract_education_multi_word_specializations_and_deduplication() -> None:
    jd_text = """
    Education Requirements:
    - Must possess a Bachelor of Technology in Artificial Intelligence and Data Science or related field.
    - Master of Science in Electrical Engineering or equivalent discipline.
    """
    education, confidence = _extract_education(jd_text)
    assert confidence > 0
    assert any("Artificial Intelligence and Data Science" in edu for edu in education)
    assert any("Electrical Engineering" in edu for edu in education)
    # Ensure generic trailers are not included
    assert not any("or related field" in edu.lower() for edu in education)
    assert not any("or equivalent discipline" in edu.lower() for edu in education)


def test_job_extractor_preserves_full_degree_phrase() -> None:
    extractor = JobDescriptionExtractor()
    text = """
    Requirements:
    - Bachelor of Technology in Artificial Intelligence and Data Science or related field.
    - B.E. in Electronics and Communication Engineering.
    """
    result = extractor.extract(text)
    education = result["education"]
    assert "Bachelor of Technology in Artificial Intelligence and Data Science" in education
    assert any("Electronics and Communication Engineering" in edu for edu in education)
    # Ensure truncated fragment is not produced
    assert "Bachelor of Technology" not in education


def test_canonicalize_degree_preserves_specialization() -> None:
    canonical_btech, rule = _canonicalize_degree("B.Tech in Artificial Intelligence and Data Science")
    assert canonical_btech == "Bachelor of Technology in Artificial Intelligence and Data Science"
    assert rule == "degree_map:Bachelor of Technology"

    canonical_be, _ = _canonicalize_degree("B.E. in Electronics and Communication Engineering")
    assert canonical_be == "Bachelor of Engineering in Electronics and Communication Engineering"

    canonical_ms, _ = _canonicalize_degree("Master of Science in Mechanical Engineering")
    assert canonical_ms == "Master of Science in Mechanical Engineering"

    canonical_phd, _ = _canonicalize_degree("Ph.D. in Computer Science")
    assert canonical_phd == "Doctor of Philosophy (PhD) in Computer Science"

    canonical_mba, _ = _canonicalize_degree("Master of Business Administration in Finance")
    assert canonical_mba == "Master of Business Administration (MBA) in Finance"


def test_canonicalize_degree_without_specialization() -> None:
    canonical, rule = _canonicalize_degree("Bachelor's Degree")
    assert canonical == "Bachelor's Degree"

    canonical_mba, _ = _canonicalize_degree("MBA")
    assert canonical_mba == "Master of Business Administration (MBA)"
