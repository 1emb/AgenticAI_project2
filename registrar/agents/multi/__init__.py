"""Multi-agent registrar: specialist agents (data, policy, advising, registration) behind a planning coordinator."""
from registrar.agents.multi.agents import AgentRuntime
from registrar.agents.multi.coordinator import Coordinator, MultiResult

__all__ = ["AgentRuntime", "Coordinator", "MultiResult"]
