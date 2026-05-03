"""
SROP ADK wiring lives in app.agents.adk_runner (root + AgentTool sub-agents).

This module keeps the routing instructions discoverable for reviewers.
See `build_agents()` and `execute_turn()` in adk_runner.py.
"""

ROOT_INSTRUCTION_OVERVIEW = """
Root agent name: srop_root
Sub-agents exposed via AgentTool: knowledge, account
Routing is performed by the LLM via native tool selection (not string parsing).
"""
