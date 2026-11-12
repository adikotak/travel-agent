from datetime import date
from decimal import Decimal

from pydantic_ai.messages import ModelMessage, ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from travel.agent.compose import (
    OptionFact,
    ReplyFacts,
    ReplyPurpose,
    compose_agent,
    render_body,
    write_prose,
)
from travel.agent.parse import (
    OptionSelection,
    ParseContext,
    TripDetails,
    parse_agent,
    parse_email,
)

CONTEXT = ParseContext(
    today=date(2026, 11, 12),
    sender_name="Priya Shah",
    sender_is_approver=False,
    current_trip="SFO -> JFK departing 2026-11-24",
    offered_options=["1. [Outbound] UA 101 one-stop — $320", "2. [Outbound] UA 202 nonstop — $520"],
)


def structured(args: dict):
    """A FunctionModel that answers with the given structured output and records instructions."""
    seen: dict[str, str] = {}

    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        seen["instructions"] = messages[-1].instructions or ""
        return ModelResponse(parts=[ToolCallPart(info.output_tools[0].name, {"intent": args})])

    return FunctionModel(respond), seen


class TestParse:
    """Parsing returns typed intents and gives the model server-known context."""

    def test_returns_typed_trip_details(self):
        """A constraint change comes back as TripDetails with only the stated fields set."""
        model, _ = structured({"kind": "trip-details", "return_date": "2026-11-26"})
        with parse_agent.override(model=model):
            intent = parse_email("Re: trip", "Can I come back Wednesday?", CONTEXT)
        assert intent == TripDetails(return_date=date(2026, 11, 26))

    def test_instructions_carry_today_and_offered_options(self):
        """The model sees today's date and the numbered options so 'option 2' resolves."""
        model, seen = structured({"kind": "option-selection", "option_numbers": [2]})
        with parse_agent.override(model=model):
            intent = parse_email("Re: trip", "Option 2 please", CONTEXT)
        assert intent == OptionSelection(option_numbers=[2])
        assert "2026-11-12" in seen["instructions"]
        assert "UA 202 nonstop" in seen["instructions"]


class TestCompose:
    """Replies are model prose plus an exact, code-rendered options block."""

    def test_options_rendered_from_facts_not_model(self):
        """Prices and flights come from the facts even if the model text says otherwise."""

        def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
            return ModelResponse(parts=[TextPart("Here are your options, the nonstop is $1.")])

        facts = ReplyFacts(
            purpose=ReplyPurpose.OPTIONS,
            recipient_name="Priya",
            trip_tag="TRIP-7",
            options=[
                OptionFact(1, "Outbound", "UA 101 SFO→ORD→JFK", Decimal("320"), True),
                OptionFact(
                    2,
                    "Outbound",
                    "UA 202 SFO→JFK nonstop",
                    Decimal("520"),
                    False,
                    policy_notes=["$520 is over the $400 short-haul budget"],
                    preference_notes=["Nonstop"],
                ),
            ],
        )
        with compose_agent.override(model=FunctionModel(respond)):
            body = render_body(write_prose(facts), facts)
        can_book, needs_approval = body.split("Needs manager approval:")
        assert "1. [Outbound] UA 101 SFO→ORD→JFK — $320" in can_book
        assert "2. [Outbound] UA 202 SFO→JFK nonstop — $520" in needs_approval
        assert "⚠ $520 is over the $400 short-haul budget" in needs_approval
        assert "TRIP-7" in body
