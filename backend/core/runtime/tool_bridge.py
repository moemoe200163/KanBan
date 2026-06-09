"""Tool Runtime Bridge — Agentic tool-use loop for LLM execution.

When the LLM returns tool_use blocks (Anthropic) or function_call (OpenAI),
this bridge:
  1. Parses the tool call
  2. Executes it via invoke_tool()
  3. Feeds the result back as a tool_result message
  4. Continues the loop until a text response or max iterations

This closes the loop between LLM tool calls and the Kanban Tool Protocol.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine, Dict, List, Optional

import httpx

from core.kanban_protocol.tools import (
    KanbanToolContext,
    ToolResult,
    invoke_tool,
)

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10
DEFAULT_TIMEOUT = 120.0


@dataclass
class ToolCall:
    """Parsed tool call from LLM response."""
    id: str
    name: str
    input: Dict[str, Any]


@dataclass
class BridgeResult:
    """Result of a tool-use bridge loop."""
    success: bool
    output: str = ""
    tool_calls_made: int = 0
    error: Optional[str] = None
    model: str = ""
    provider: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0


# ---------------------------------------------------------------------------
# Tool schema conversion
# ---------------------------------------------------------------------------

def kanban_tools_as_openai_functions(
    tool_schemas: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert TOOL_SCHEMAS to OpenAI function-calling format."""
    functions = []
    for name, schema in tool_schemas.items():
        functions.append({
            "type": "function",
            "function": {
                "name": name,
                "description": _tool_description(name),
                "parameters": schema,
            },
        })
    return functions


def kanban_tools_as_anthropic_tools(
    tool_schemas: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Convert TOOL_SCHEMAS to Anthropic tool-use format."""
    tools = []
    for name, schema in tool_schemas.items():
        tools.append({
            "name": name,
            "description": _tool_description(name),
            "input_schema": schema,
        })
    return tools


def _tool_description(name: str) -> str:
    """Get a human-readable description for a kanban tool."""
    descriptions = {
        "kanban_list": "List issues on a board, optionally filtered by status.",
        "kanban_show": "Show detailed information about a single issue.",
        "kanban_create": "Create a new issue on the board.",
        "kanban_comment": "Add a comment or progress note to an issue.",
        "kanban_block": "Block an issue with a reason.",
        "kanban_unblock": "Unblock a blocked issue.",
        "kanban_complete": "Mark work as done and create a review handoff.",
        "kanban_heartbeat": "Send a heartbeat to keep the run alive.",
        "kanban_link": "Attach a URL link (PR, file, resource) to an issue.",
    }
    return descriptions.get(name, f"Kanban tool: {name}")


# ---------------------------------------------------------------------------
# Tool call parsing
# ---------------------------------------------------------------------------

def parse_anthropic_tool_use(content_blocks: List[Dict[str, Any]]) -> List[ToolCall]:
    """Extract tool_use blocks from Anthropic response content."""
    calls = []
    for block in content_blocks:
        if block.get("type") == "tool_use":
            calls.append(ToolCall(
                id=block["id"],
                name=block["name"],
                input=block.get("input", {}),
            ))
    return calls


def parse_openai_tool_calls(message: Dict[str, Any]) -> List[ToolCall]:
    """Extract tool_calls from OpenAI response message."""
    calls = []
    # New-style: message.tool_calls
    for tc in message.get("tool_calls", []):
        func = tc.get("function", {})
        args = func.get("arguments", "{}")
        try:
            parsed_args = json.loads(args) if isinstance(args, str) else args
        except json.JSONDecodeError:
            parsed_args = {}
        calls.append(ToolCall(
            id=tc.get("id", f"call_{int(time.time()*1000)}"),
            name=func.get("name", ""),
            input=parsed_args,
        ))
    # Legacy: message.function_call
    fc = message.get("function_call")
    if fc and not calls:
        args = fc.get("arguments", "{}")
        try:
            parsed_args = json.loads(args) if isinstance(args, str) else args
        except json.JSONDecodeError:
            parsed_args = {}
        calls.append(ToolCall(
            id=f"call_{int(time.time()*1000)}",
            name=fc.get("name", ""),
            input=parsed_args,
        ))
    return calls


# ---------------------------------------------------------------------------
# Core bridge loop
# ---------------------------------------------------------------------------

async def run_tool_loop(
    *,
    provider_id: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    tool_schemas: Dict[str, Dict[str, Any]],
    board_id: str = "board-default",
    issue_id: Optional[str] = None,
    issue_key: Optional[str] = None,
    actor: str = "agent",
    agent_role: str = "safe-runner",
    run_id: Optional[str] = None,
    on_log: Callable[[str], Coroutine[Any, Any, None]],
    max_iterations: int = MAX_TOOL_ITERATIONS,
    timeout: float = DEFAULT_TIMEOUT,
) -> BridgeResult:
    """Execute an agentic tool-use loop.

    Sends the prompt to the LLM with kanban tool definitions.
    If the LLM responds with tool calls, executes them via invoke_tool()
    and feeds results back. Repeats until a text response or max iterations.
    """
    from db.repository import get_llm_provider_config_with_key
    from core.llm.crypto import decrypt_api_key

    # --- Resolve provider config ---
    config = await get_llm_provider_config_with_key(provider_id)
    if not config:
        return BridgeResult(success=False, error=f"Provider not found: {provider_id}")

    api_key_encrypted = config.get("api_key_encrypted", "")
    api_key = decrypt_api_key(api_key_encrypted) if api_key_encrypted else ""
    if not api_key:
        import os
        from core.runtime.api_model_executor import _env_var_for_provider
        api_key = os.getenv(_env_var_for_provider(provider_id), "")

    if not api_key:
        return BridgeResult(success=False, error=f"No API key for {provider_id}")

    base_url = config.get("base_url", "")
    endpoint_path = config.get("endpoint_path", "/chat/completions")
    api_shape = config.get("api_shape", "openai-chat")
    auth_type = config.get("auth_type", "bearer")
    actual_model = model or config.get("model", "")

    await on_log(f"Tool bridge: {provider_id}/{actual_model} shape={api_shape}")
    await on_log(f"Tools available: {list(tool_schemas.keys())}")

    # --- Build tool definitions ---
    if api_shape == "anthropic-messages":
        api_tools = kanban_tools_as_anthropic_tools(tool_schemas)
    else:
        api_tools = kanban_tools_as_openai_functions(tool_schemas)

    # --- Initialize conversation ---
    messages: List[Dict[str, Any]] = [{"role": "user", "content": user_prompt}]

    start = time.monotonic()
    total_prompt_tokens = 0
    total_completion_tokens = 0
    iterations = 0
    final_text = ""

    for iteration in range(max_iterations):
        iterations = iteration + 1

        try:
            if api_shape == "anthropic-messages":
                response_data = await _call_anthropic_with_tools(
                    base_url=base_url,
                    endpoint_path=endpoint_path,
                    model=actual_model,
                    api_key=api_key,
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=api_tools,
                    timeout=timeout,
                )
            else:
                response_data = await _call_openai_with_tools(
                    base_url=base_url,
                    endpoint_path=endpoint_path,
                    model=actual_model,
                    api_key=api_key,
                    auth_type=auth_type,
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=api_tools,
                    timeout=timeout,
                )
        except Exception as exc:
            await on_log(f"Bridge API error at iteration {iterations}: {exc}")
            return BridgeResult(
                success=False,
                error=str(exc),
                tool_calls_made=iterations - 1,
                model=actual_model,
                provider=provider_id,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        if not response_data.get("success"):
            await on_log(f"Bridge API failed: {response_data.get('error')}")
            return BridgeResult(
                success=False,
                error=response_data.get("error", "Unknown API error"),
                tool_calls_made=iterations - 1,
                model=actual_model,
                provider=provider_id,
                prompt_tokens=total_prompt_tokens,
                completion_tokens=total_completion_tokens,
                latency_ms=int((time.monotonic() - start) * 1000),
            )

        total_prompt_tokens += response_data.get("prompt_tokens", 0)
        total_completion_tokens += response_data.get("completion_tokens", 0)

        # --- Parse tool calls from response ---
        if api_shape == "anthropic-messages":
            tool_calls = parse_anthropic_tool_use(response_data.get("content_blocks", []))
        else:
            tool_calls = parse_openai_tool_calls(response_data.get("message", {}))

        # --- No tool calls → return final text ---
        if not tool_calls:
            final_text = response_data.get("text", "")
            await on_log(f"Bridge complete after {iterations} iteration(s), {len(final_text)} chars")
            break

        # --- Execute tool calls ---
        await on_log(f"Iteration {iterations}: {len(tool_calls)} tool call(s)")

        # Add assistant message to conversation (with tool_use blocks)
        messages.append(response_data.get("assistant_message", {"role": "assistant", "content": ""}))

        for tc in tool_calls:
            await on_log(f"  → {tc.name}({json.dumps(tc.input, default=str)[:200]})")

            # Execute via kanban tool protocol
            ctx = KanbanToolContext(
                board_id=board_id,
                issue_id=issue_id,
                issue_key=issue_key,
                actor=actor,
                agent_role=agent_role,
                payload=tc.input,
            )
            result: ToolResult = await invoke_tool(tc.name, ctx)

            # --- Audit trail ---
            if run_id:
                try:
                    from db import repository as repo
                    import uuid
                    event_type = "tool_call_completed" if result.ok else "tool_call_failed"
                    await repo.append_run_event(
                        id=str(uuid.uuid4()),
                        run_id=run_id,
                        event_type=event_type,
                        message=f"tool={tc.name} ok={result.ok}",
                        extra_metadata={
                            "tool_name": tc.name,
                            "actor": actor,
                            "agent_role": agent_role,
                            "board_id": board_id,
                            "ok": result.ok,
                            "iteration": iterations,
                        },
                    )
                except Exception:
                    logger.warning("Failed to write bridge audit event for run %s", run_id)

            status = "ok" if result.ok else f"error: {result.error}"
            await on_log(f"  ← {status}")

            # Add tool result to conversation
            if api_shape == "anthropic-messages":
                messages.append({
                    "role": "user",
                    "content": [{
                        "type": "tool_result",
                        "tool_use_id": tc.id,
                        "content": json.dumps(result.data) if result.ok else f"Error: {result.error}",
                    }],
                })
            else:
                tool_result_content = json.dumps(result.data) if result.ok else f"Error: {result.error}"
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": tool_result_content,
                })
    else:
        await on_log(f"Bridge hit max iterations ({max_iterations})")
        final_text = f"Max tool iterations ({max_iterations}) reached"

    latency_ms = int((time.monotonic() - start) * 1000)
    await on_log(f"Bridge finished: {iterations} iterations, {total_prompt_tokens}+{total_completion_tokens} tokens, {latency_ms}ms")

    return BridgeResult(
        success=True,
        output=final_text,
        tool_calls_made=iterations,
        model=actual_model,
        provider=provider_id,
        prompt_tokens=total_prompt_tokens,
        completion_tokens=total_completion_tokens,
        latency_ms=latency_ms,
    )


# ---------------------------------------------------------------------------
# API call helpers (with tool support)
# ---------------------------------------------------------------------------

async def _call_anthropic_with_tools(
    *,
    base_url: str,
    endpoint_path: str,
    model: str,
    api_key: str,
    system_prompt: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    timeout: float,
) -> Dict[str, Any]:
    """Call Anthropic Messages API with tools enabled."""
    url = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }

    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": 4096,
    }
    if system_prompt:
        body["system"] = system_prompt
    if tools:
        body["tools"] = tools

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=body)

        if resp.status_code == 200:
            data = resp.json()
            content_blocks = data.get("content", [])

            # Extract text and tool_use blocks
            text_parts = []
            for block in content_blocks:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))

            usage = data.get("usage", {})

            # Build assistant message for conversation history
            assistant_message = {"role": "assistant", "content": content_blocks}

            return {
                "success": True,
                "text": "\n".join(text_parts),
                "content_blocks": content_blocks,
                "assistant_message": assistant_message,
                "prompt_tokens": usage.get("input_tokens", 0),
                "completion_tokens": usage.get("output_tokens", 0),
            }

        return {
            "success": False,
            "error": f"HTTP {resp.status_code}: {resp.text[:500]}",
        }


async def _call_openai_with_tools(
    *,
    base_url: str,
    endpoint_path: str,
    model: str,
    api_key: str,
    auth_type: str,
    system_prompt: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    timeout: float,
) -> Dict[str, Any]:
    """Call OpenAI-compatible chat API with tools/functions enabled."""
    from core.runtime.api_model_executor import _build_auth_headers

    url = f"{base_url.rstrip('/')}{endpoint_path}"
    headers = _build_auth_headers(auth_type, api_key)
    headers["Content-Type"] = "application/json"

    # Build messages with system prompt
    api_messages = []
    if system_prompt:
        api_messages.append({"role": "system", "content": system_prompt})
    api_messages.extend(messages)

    body: Dict[str, Any] = {
        "model": model,
        "messages": api_messages,
        "max_tokens": 4096,
    }
    if tools:
        body["tools"] = tools

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, headers=headers, json=body)

        if resp.status_code == 200:
            data = resp.json()
            choices = data.get("choices", [])
            if not choices:
                return {"success": False, "error": "No choices in response"}

            message = choices[0].get("message", {})
            text = message.get("content", "") or ""
            usage = data.get("usage", {})

            return {
                "success": True,
                "text": text,
                "message": message,
                "assistant_message": message,
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }

        return {
            "success": False,
            "error": f"HTTP {resp.status_code}: {resp.text[:500]}",
        }
