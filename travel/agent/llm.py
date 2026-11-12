from django.conf import settings
from pydantic_ai.models.openai import OpenAIResponsesModel
from pydantic_ai.providers.openai import OpenAIProvider


def chat_model() -> OpenAIResponsesModel:
    """The configured OpenAI model; agents receive it per run so tests can override it.

    Uses the Responses API: reasoning models reject function tools (which carry our
    structured outputs) on Chat Completions.
    """
    return OpenAIResponsesModel(
        settings.OPENAI_MODEL, provider=OpenAIProvider(api_key=settings.OPENAI_API_KEY)
    )
