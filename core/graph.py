import os
from langgraph.graph import StateGraph, END

from core.state import GraphState
from core.nodes.executor import executor_node
from core.nodes.critic import critic_node
from core.nodes.refiner import refiner_node
from core.nodes.meta import meta_node
from core.router import route_after_critic


def build_graph() -> StateGraph:
    graph = StateGraph(GraphState)

    graph.add_node("executor", executor_node)
    graph.add_node("critic", critic_node)
    graph.add_node("refiner", refiner_node)
    graph.add_node("meta", meta_node)

    graph.set_entry_point("executor")
    graph.add_edge("executor", "critic")

    graph.add_conditional_edges(
        "critic",
        route_after_critic,
        {
            "refiner": "refiner",
            "meta": "meta",
        },
    )

    graph.add_edge("refiner", "executor")
    graph.add_edge("meta", END)

    return graph


def create_runnable(max_iterations: int = 5):
    graph = build_graph()
    return graph.compile()
