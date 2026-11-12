from collections import deque

import pytest
from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from travel.agent.compose import compose_agent
from travel.agent.parse import parse_agent


def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true", help="run tests/live against the real OpenAI model"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip = pytest.mark.skip(reason="real-model test; run with --live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def fake_openai_key(request, settings):
    """Agents build their OpenAI model per run; tests override it, so the key is never used.

    A real call made by mistake fails authentication instead of spending money. Live tests
    keep the configured key.
    """
    if "live" not in request.keywords:
        settings.OPENAI_API_KEY = "test-key-not-real"


@pytest.fixture
def fixed_prose():
    """Reply prose is a fixed string; options, questions, and itinerary still render."""

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart("Message.")])

    with compose_agent.override(model=FunctionModel(respond)):
        yield


@pytest.fixture
def parses():
    """Queue the intents the parser will return, one per inbound email, in order."""
    queue: deque[dict] = deque()

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        return ModelResponse(
            parts=[ToolCallPart(info.output_tools[0].name, {"intent": queue.popleft()})]
        )

    with parse_agent.override(model=FunctionModel(respond)):
        yield queue
