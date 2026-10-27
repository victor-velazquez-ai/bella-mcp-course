import json
import subprocess

import pytest

from bella_mcp import brain
from bella_mcp.brain import Brain, BrainUnavailable
from bella_mcp.db import _relative_periods


@pytest.mark.parametrize("as_of, last_month, last_quarter", [
    ("2026-09-30", "2026-09-01 to 2026-09-30", "2026-07-01 to 2026-09-30"),  # the demo data: a quarter end
    ("2026-11-15", "2026-10-01 to 2026-10-31", "2026-07-01 to 2026-09-30"),
    ("2027-01-15", "2026-12-01 to 2026-12-31", "2026-10-01 to 2026-12-31"),
])
def test_relative_periods_are_explicit_dates(as_of, last_month, last_quarter):
    text = _relative_periods(as_of)
    assert f"last month = {last_month}" in text and f"last quarter = {last_quarter}" in text


@pytest.fixture
def no_keys(monkeypatch):
    for var in ("MOCK", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "BELLA_BRAIN", "BELLA_MODEL", "BELLA_CLAUDE_BIN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(brain.shutil, "which", lambda name: None)
    return monkeypatch


def test_provider_order(no_keys):
    assert Brain().provider == "demo"
    no_keys.setenv("BELLA_CLAUDE_BIN", "claude")
    assert (Brain().provider, Brain().model) == ("claude-code", "sonnet")
    no_keys.setenv("OPENAI_API_KEY", "sk-test")
    assert Brain().provider == "openai"
    no_keys.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert Brain().provider == "anthropic"
    no_keys.setenv("MOCK", "1")
    assert Brain().provider == "demo"


def test_explicit_choice_is_validated(no_keys):
    no_keys.setenv("BELLA_BRAIN", "gemini")
    with pytest.raises(SystemExit):
        Brain()
    no_keys.setenv("BELLA_BRAIN", "claude-code")
    with pytest.raises(SystemExit, match="BELLA_CLAUDE_BIN"):
        Brain()


def fake_claude(no_keys, stdout: str, returncode: int = 0) -> list:
    """Stand-in for `claude -p`: records how it was called, returns canned output."""
    calls = []

    def run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr="")

    no_keys.setenv("BELLA_CLAUDE_BIN", "claude")
    no_keys.setattr(brain.subprocess, "run", run)
    return calls


def test_subscription_brain_keeps_user_text_off_the_command_line(no_keys):
    question = 'top products" & del /q * | "'
    answer = {"sql": "SELECT 1", "explanation": "one"}
    calls = fake_claude(no_keys, json.dumps({"is_error": False, "result": json.dumps(answer)}))
    draft = Brain().write_sql(question, "schema")
    cmd, kwargs = calls[0]
    assert (draft.sql, draft.source) == ("SELECT 1", "claude-code")
    assert kwargs["input"] == question and question not in " ".join(cmd)
    assert cmd[cmd.index("--tools") + 1] == "" and "--strict-mcp-config" in cmd


def test_subscription_brain_failure_tells_client_what_to_do(no_keys):
    fake_claude(no_keys, json.dumps({"is_error": True, "result": "Not logged in"}), returncode=1)
    with pytest.raises(BrainUnavailable, match="Not logged in.*logged in, or send a read-only SQL"):
        Brain().write_sql("revenue?", "schema")
