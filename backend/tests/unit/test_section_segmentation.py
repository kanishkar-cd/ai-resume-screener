from app.services.pipeline.extraction_pipeline import match_terms, segment_sections


def test_section_segmentation_supports_aliases_and_colons() -> None:
    sections = segment_sections("Jane Doe\nTECHNICAL SKILLS:\nPython\nWORK HISTORY\nAcme Corp")
    assert sections["header"] == "Jane Doe"
    assert sections["skills"] == "Python"
    assert sections["experience"] == "Acme Corp"


def test_gazetteer_matching_is_case_insensitive_and_boundary_aware() -> None:
    assert match_terms("python, SQL and PostgreSQL", ("Python", "SQL", "PostgreSQL")) == [
        "Python", "SQL", "PostgreSQL"
    ]
    assert match_terms("NoSQL", ("SQL",)) == []
