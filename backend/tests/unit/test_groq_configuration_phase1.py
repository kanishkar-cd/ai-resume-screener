from app.core.config import Settings
from app.services.llm.batch_pipeline import GroqBatchExecutor
from app.services.matching_service import GroqMatchEvaluator, SmartMatchEvaluator


def test_configuration_a_indexed_keys():
    """
    Test A — Indexed keys:
    GROQ_API_KEY_1 = key1
    GROQ_API_KEY_2 = key2
    GROQ_API_KEY_3 = empty
    GROQ_API_KEY = empty
    ENABLE_HYBRID_MATCHING = true
    Expected:
    normalized Groq keys = 2
    Groq enabled = true
    """
    settings = Settings(
        GROQ_API_KEY_1="fake-key-1",
        GROQ_API_KEY_2="fake-key-2",
        GROQ_API_KEY_3="",
        GROQ_API_KEY=None,
        ENABLE_HYBRID_MATCHING=True,
    )

    assert len(settings.groq_keys) == 2
    assert settings.groq_is_configured is True
    assert settings.primary_groq_api_key == "fake-key-1"
    # Legacy backward-compatibility populated
    assert settings.GROQ_API_KEY == "fake-key-1"

    executor = GroqBatchExecutor(settings=settings)
    assert executor.enabled is True

    evaluator = GroqMatchEvaluator(settings=settings)
    assert evaluator.enabled is True

    smart_evaluator = SmartMatchEvaluator(settings=settings)
    assert smart_evaluator.groq.enabled is True


def test_configuration_b_legacy_key():
    """
    Test B — Legacy key:
    GROQ_API_KEY = key
    GROQ_API_KEY_1 = empty
    GROQ_API_KEY_2 = empty
    GROQ_API_KEY_3 = empty
    ENABLE_HYBRID_MATCHING = true
    Expected:
    normalized Groq keys = 1
    Groq enabled = true
    """
    settings = Settings(
        GROQ_API_KEY="fake-legacy-key",
        GROQ_API_KEY_1=None,
        GROQ_API_KEY_2=None,
        GROQ_API_KEY_3=None,
        ENABLE_HYBRID_MATCHING=True,
    )

    assert len(settings.groq_keys) == 1
    assert settings.groq_is_configured is True
    assert settings.primary_groq_api_key == "fake-legacy-key"
    assert settings.GROQ_API_KEY == "fake-legacy-key"

    executor = GroqBatchExecutor(settings=settings)
    assert executor.enabled is True

    evaluator = GroqMatchEvaluator(settings=settings)
    assert evaluator.enabled is True


def test_configuration_c_mixed_and_duplicate_keys():
    """
    Test C — Mixed keys:
    GROQ_API_KEY = key1
    GROQ_API_KEY_1 = key1
    GROQ_API_KEY_2 = key2
    Expected:
    normalized Groq keys = 2 (duplicates removed, order preserved)
    """
    settings = Settings(
        GROQ_API_KEY="fake-key-1",
        GROQ_API_KEY_1="fake-key-1",
        GROQ_API_KEY_2="fake-key-2",
        GROQ_API_KEY_3="   ",  # whitespace only should be stripped
        ENABLE_HYBRID_MATCHING=True,
    )

    assert len(settings.groq_keys) == 2
    assert settings.groq_keys == ["fake-key-1", "fake-key-2"]
    assert settings.groq_is_configured is True
    assert settings.primary_groq_api_key == "fake-key-1"

    executor = GroqBatchExecutor(settings=settings)
    assert executor.enabled is True

    evaluator = GroqMatchEvaluator(settings=settings)
    assert evaluator.enabled is True


def test_configuration_d_no_keys():
    """
    Test D — No keys:
    GROQ_API_KEY = empty
    GROQ_API_KEY_1 = empty
    GROQ_API_KEY_2 = empty
    GROQ_API_KEY_3 = empty
    ENABLE_HYBRID_MATCHING = true
    Expected:
    Groq enabled = false (fails gracefully)
    """
    settings = Settings(
        GROQ_API_KEY=None,
        GROQ_API_KEY_1=None,
        GROQ_API_KEY_2="",
        GROQ_API_KEY_3="   ",
        ENABLE_HYBRID_MATCHING=True,
    )

    assert len(settings.groq_keys) == 0
    assert settings.groq_is_configured is False
    assert settings.primary_groq_api_key is None
    assert settings.GROQ_API_KEY is None

    executor = GroqBatchExecutor(settings=settings)
    assert executor.enabled is False

    evaluator = GroqMatchEvaluator(settings=settings)
    assert evaluator.enabled is False


def test_configuration_e_hybrid_matching_disabled():
    """
    Test E — Hybrid matching disabled:
    valid Groq key exists
    ENABLE_HYBRID_MATCHING = false
    Expected:
    Groq enabled = false
    """
    settings = Settings(
        GROQ_API_KEY_1="fake-key-1",
        GROQ_API_KEY_2="fake-key-2",
        ENABLE_HYBRID_MATCHING=False,
    )

    assert len(settings.groq_keys) == 2
    assert settings.groq_is_configured is True

    executor = GroqBatchExecutor(settings=settings)
    assert executor.enabled is False

    evaluator = GroqMatchEvaluator(settings=settings)
    assert evaluator.enabled is False

