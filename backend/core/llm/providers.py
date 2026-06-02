"""
LLM Provider definitions.

Each provider declares its metadata, capabilities, auth requirements,
and adapter type. The registry uses these definitions to populate the
provider list without requiring real API keys.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LLMProviderDef:
    id: str
    name: str
    adapter: str  # api-chat | api-responses | cli | local-safe-runner
    capabilities: List[str]
    auth_type: str  # api_key | oauth | cli_path | none
    auth_env_var: Optional[str] = None
    default_model: Optional[str] = None
    models: List[str] = field(default_factory=list)
    enabled: bool = True


PROVIDERS: List[LLMProviderDef] = [
    LLMProviderDef(
        id="openai",
        name="OpenAI",
        adapter="api-chat",
        capabilities=["chat", "code", "tool-use", "streaming", "vision"],
        auth_type="api_key",
        auth_env_var="OPENAI_API_KEY",
        default_model="gpt-4o",
        models=["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o1", "o1-mini", "o3-mini"],
    ),
    LLMProviderDef(
        id="openai-codex",
        name="OpenAI Codex",
        adapter="api-responses",
        capabilities=["chat", "code", "tool-use", "streaming"],
        auth_type="api_key",
        auth_env_var="CODEX_API_KEY",
        default_model="codex-mini-latest",
        models=["codex-mini-latest", "o4-mini"],
    ),
    LLMProviderDef(
        id="anthropic",
        name="Anthropic",
        adapter="api-chat",
        capabilities=["chat", "code", "tool-use", "streaming", "vision"],
        auth_type="api_key",
        auth_env_var="ANTHROPIC_API_KEY",
        default_model="claude-sonnet-4-20250514",
        models=[
            "claude-opus-4-20250514",
            "claude-sonnet-4-20250514",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
        ],
    ),
    LLMProviderDef(
        id="gemini",
        name="Google Gemini",
        adapter="api-chat",
        capabilities=["chat", "code", "tool-use", "streaming", "vision"],
        auth_type="api_key",
        auth_env_var="GEMINI_API_KEY",
        default_model="gemini-2.5-pro",
        models=["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.0-flash"],
    ),
    LLMProviderDef(
        id="minimax",
        name="MiniMax",
        adapter="api-chat",
        capabilities=["chat", "code", "streaming"],
        auth_type="api_key",
        auth_env_var="MINIMAX_API_KEY",
        default_model="MiniMax-M1",
        models=["MiniMax-M1", "abab7-chat"],
    ),
    LLMProviderDef(
        id="claude-code",
        name="Claude Code CLI",
        adapter="cli",
        capabilities=["chat", "code", "tool-use", "streaming", "cli"],
        auth_type="cli_path",
        auth_env_var="CLAUDE_CODE_PATH",
        default_model=None,
        models=[],
    ),
    LLMProviderDef(
        id="codex-cli",
        name="Codex CLI",
        adapter="cli",
        capabilities=["chat", "code", "tool-use", "streaming", "cli"],
        auth_type="cli_path",
        auth_env_var="CODEX_CLI_PATH",
        default_model=None,
        models=[],
    ),
    LLMProviderDef(
        id="safe-runner",
        name="Safe Runner",
        adapter="local-safe-runner",
        capabilities=["code"],
        auth_type="none",
        auth_env_var=None,
        default_model=None,
        models=[],
        enabled=True,
    ),
]

PROVIDER_MAP = {p.id: p for p in PROVIDERS}
