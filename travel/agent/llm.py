from django.conf import settings
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider


def chat_model() -> OpenAIChatModel:
    """The configured OpenAI model; agents receive it per run so tests can override it."""
    return OpenAIChatModel(
        settings.OPENAI_MODEL, provider=OpenAIProvider(api_key=settings.OPENAI_API_KEY)
    )
