"""Least-privilege tool scopes for analyst agents (constitution VIII; contracts/rest-and-mcp.md)."""

import asyncio
from types import SimpleNamespace

from automind import mcp_server
from automind.orchestration.agents import SCOPES, prompt_name, scoped_tools
from automind.orchestration.prompts import load_all


def test_every_scoped_tool_exists_on_the_mcp_server():
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    for role, tools in SCOPES.items():
        assert tools <= names, role


def test_scopes_follow_the_contract():
    assert "get_engineering" in SCOPES["reporter_expert"] and "get_engineering" not in SCOPES["reporter_buyer"]
    assert "compute_tco" in SCOPES["reporter_buyer"] and "compute_tco" not in SCOPES["reporter_performance"]
    assert "get_manufacturer" not in SCOPES["answerer"]
    tools = [SimpleNamespace(name=n) for n in ("get_case", "get_engineering", "compute_tco")]
    assert [t.name for t in scoped_tools(tools, "reporter_buyer")] == ["get_case", "compute_tco"]


def test_persona_prompts_exist_and_format():
    prompts = load_all()
    for persona in ("EXPERT", "PERFORMANCE", "BUYER", "UNKNOWN"):
        text = prompts[prompt_name("reporter", persona)]
        assert "{case_summary}" in text and text.format(case_summary="x", language="ru", persona=persona)
