"""Understandable OpenAI tool-calling loop with a zero-cost mock fallback."""

import json
from typing import Any

from openai import (
    APIError,
    ContentFilterFinishReasonError,
    LengthFinishReasonError,
    OpenAI,
)
from pydantic import ValidationError

from backend.config import settings
from backend.schemas import AnalysisRequest, AnalysisResponse
from backend.tools import (
    TOOL_DEFINITIONS,
    calculate_metric,
    get_record_details,
    recommend_action,
    run_tool,
)


class AgentError(RuntimeError):
    """Raised when the AI workflow cannot produce a valid result."""


# CHANGE THIS AFTER CHALLENGE REVEAL
AGENT_INSTRUCTIONS = """
You are a concise decision assistant for a generic hackathon demo.
Use the provided tools to inspect the requested sample record, calculate its metric,
and recommend an action. Call every available tool exactly once with the record_id
provided by the user. Do not invent record data.
""".strip()

FINAL_INSTRUCTIONS = """
All required tools have been executed. Produce the final decision using only the
user input and tool outputs. Keep reasoning_summary to two short sentences, express
confidence as a number from 0 to 1, set mode to "openai", and list the tools used.
Do not expose hidden chain-of-thought; provide only a concise decision rationale.
""".strip()

MAX_TOOL_ROUNDS = 3


def _mock_analysis(request: AnalysisRequest) -> AnalysisResponse:
    """Run the full flow locally so the UI and API work without credits."""

    details = get_record_details(request.record_id)
    metric = calculate_metric(request.record_id)
    action = recommend_action(request.record_id)

    if action["urgency"] == "high":
        decision = "prioritize"
    elif action["urgency"] == "medium":
        decision = "review"
    else:
        decision = "monitor"

    return AnalysisResponse(
        decision=decision,
        reasoning_summary=(
            f"{request.record_id} is at {metric['attainment_percent']}% of target "
            f"with status '{details['status']}'. The deterministic sample rules "
            f"assign {action['urgency']} urgency."
        ),
        confidence=0.93,
        recommended_action=action["action"],
        tools_used=[
            "get_record_details",
            "calculate_metric",
            "recommend_action",
        ],
        mode="mock",
    )


def _call_openai(request: AnalysisRequest) -> AnalysisResponse:
    if settings.openai_api_key is None:
        raise AgentError("OPENAI_API_KEY is missing; use mock mode instead.")

    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.openai_timeout_seconds,
        max_retries=1,
    )
    input_items: list[Any] = [
        {
            "role": "user",
            "content": (
                f"Record ID: {request.record_id}\n"
                f"User request: {request.input_text}"
            ),
        }
    ]
    remaining_tools = {tool["name"]: tool for tool in TOOL_DEFINITIONS}
    tools_used: list[str] = []

    try:
        for _ in range(MAX_TOOL_ROUNDS):
            offered_tool_names = set(remaining_tools)
            response = client.responses.create(
                model=settings.openai_model,
                instructions=AGENT_INSTRUCTIONS,
                input=input_items,
                tools=list(remaining_tools.values()),
                tool_choice="required",
                parallel_tool_calls=True,
            )
            input_items.extend(response.output)

            tool_calls = [
                item for item in response.output if item.type == "function_call"
            ]
            if not tool_calls:
                raise AgentError("The model did not request any of the required tools.")

            for tool_call in tool_calls:
                if tool_call.name not in offered_tool_names:
                    raise AgentError(
                        f"The model requested an unavailable tool: {tool_call.name}."
                    )

                try:
                    arguments = json.loads(tool_call.arguments)
                except json.JSONDecodeError as exc:
                    raise AgentError(
                        f"Tool '{tool_call.name}' returned invalid JSON arguments."
                    ) from exc

                if not isinstance(arguments, dict):
                    raise AgentError(
                        f"Tool '{tool_call.name}' arguments must be a JSON object."
                    )

                tool_result = run_tool(tool_call.name, arguments)
                input_items.append(
                    {
                        "type": "function_call_output",
                        "call_id": tool_call.call_id,
                        "output": json.dumps(tool_result),
                    }
                )
                if tool_call.name not in tools_used:
                    tools_used.append(tool_call.name)
                remaining_tools.pop(tool_call.name, None)

            if not remaining_tools:
                break
        else:
            raise AgentError("The agent exceeded the tool-call round limit.")

        final_response = client.responses.parse(
            model=settings.openai_model,
            instructions=f"{AGENT_INSTRUCTIONS}\n\n{FINAL_INSTRUCTIONS}",
            input=input_items,
            text_format=AnalysisResponse,
        )
    except APIError as exc:
        raise AgentError(f"OpenAI API request failed: {exc}") from exc
    except (ContentFilterFinishReasonError, LengthFinishReasonError) as exc:
        raise AgentError(f"OpenAI could not complete the structured result: {exc}") from exc
    except ValidationError as exc:
        raise AgentError(f"OpenAI returned an invalid structured result: {exc}") from exc

    parsed = final_response.output_parsed
    if parsed is None:
        raise AgentError("OpenAI returned no structured analysis result.")

    return parsed.model_copy(update={"tools_used": tools_used, "mode": "openai"})


def analyze(request: AnalysisRequest) -> AnalysisResponse:
    """Select mock or OpenAI mode and return the same response contract."""

    if settings.mock_mode:
        return _mock_analysis(request)
    return _call_openai(request)
