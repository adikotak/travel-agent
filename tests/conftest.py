import pytest


@pytest.fixture(autouse=True)
def fake_openai_key(settings):
    """Agents build their OpenAI model per run; tests override it, so the key is never used.

    A real call made by mistake fails authentication instead of spending money.
    """
    settings.OPENAI_API_KEY = "test-key-not-real"
