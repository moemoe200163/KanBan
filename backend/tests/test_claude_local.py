import pytest
from core.adapters.claude_local import ClaudeLocalAdapter


def test_adapter_supported_harnesses():
    adapter = ClaudeLocalAdapter(config={"github_token": "test"})
    assert adapter.supported_harnesses == ["claude-code"]


def test_adapter_init_with_defaults():
    adapter = ClaudeLocalAdapter()
    assert adapter.claude_path == "claude"
    assert adapter.timeout == 300


def test_adapter_init_with_custom_config():
    adapter = ClaudeLocalAdapter(config={"claude_path": "/custom/path", "timeout": 600})
    assert adapter.claude_path == "/custom/path"
    assert adapter.timeout == 600