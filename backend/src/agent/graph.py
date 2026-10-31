from langgraph.graph import StateGraph, START, END
from config.db import get_checkpointer
from models.models import RecoveryState
from agent.nodes import (
    AgentState,
    compliance_guardrail,
    route_after_compliance,
    decide_event,
    decide_reply,
    execute,
    audit,
    should_continue,
    escalate_gate,
    after_execute,
)

_agent_app = None

def get_compiled_agent():
    """
    Returns the compiled StateGraph application singleton.
    Preserves compiled graph execution plans and checkpointer connection.
    """
    global _agent_app
    if _agent_app is None:
        workflow = StateGraph(AgentState)

        workflow.add_node("compliance_guardrail", compliance_guardrail)
        workflow.add_node("decide_event", decide_event)
        workflow.add_node("decide_reply", decide_reply)
        workflow.add_node("escalate_gate", escalate_gate)
        workflow.add_node("execute", execute)
        workflow.add_node("audit", audit)

        # 1. Pre-Flight Compliance Guardrail runs FIRST on every turn
        workflow.add_edge(START, "compliance_guardrail")

        # 2. Route based on compliance validation (contact window, active session, case type)
        workflow.add_conditional_edges(
            "compliance_guardrail",
            route_after_compliance,
            {
                "decide_event": "decide_event",
                "decide_reply": "decide_reply",
                "audit": "audit",
            }
        )
        
        # Deterministic pipeline executes directly (<10ms) and routes straight to audit
        workflow.add_edge("decide_event", "audit")
        
        # Conversational agent continues with ToolNode and HIL gate
        workflow.add_conditional_edges(
            "decide_reply",
            should_continue,
            {
                "execute": "execute",
                "escalate_gate": "escalate_gate",
                "audit": "audit"
            }
        )
        
        workflow.add_edge("escalate_gate", "execute")
        
        workflow.add_conditional_edges(
            "execute", 
            after_execute,
            {
                "decide_reply": "decide_reply",
                "audit": "audit"
            }
        )
        
        workflow.add_edge("audit", END)

        # Compile the graph with native Human-in-the-Loop breakpoint
        _agent_app = workflow.compile(
            checkpointer=get_checkpointer(),
            interrupt_before=["escalate_gate"]
        )

    return _agent_app

def build_agent(state: RecoveryState | None = None):
    """
    Returns the singleton compiled revenue recovery agent StateGraph.
    """
    return get_compiled_agent()
