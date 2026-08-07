from app.services.pipeline.normalization_pipeline import normalize_text


def test_normalization_pipeline_cleans_and_counts_text() -> None:
    result = normalize_text(
        "  Senior\t Python  Engineer\r\n\x00Builds   APIs\r\n\r\n\r\nFastAPI "
    )

    assert result.normalized_text == "Senior Python Engineer\nBuilds APIs\n\nFastAPI"
    assert result.word_count == 6
    assert result.character_count == len(result.normalized_text)
    assert result.language


def test_language_detection_falls_back_for_ambiguous_text() -> None:
    result = normalize_text("x")
    assert result.language == "en"
