"""DAG graph validation utilities for workflow definitions.

Provides cycle detection via DFS coloring, depth validation via
topological sort, and dependency graph construction from step lists.
"""

from collections import defaultdict

from src.engine.models import StepDefinition
from src.lib.utils import AppError

MAX_DEPTH = 20


def build_dependency_graph(
    steps: list[StepDefinition],
) -> dict[str, list[str]]:
    """Build an adjacency list from step dependencies.

    Returns:
        Dict mapping each step ID to its list of dependency step IDs.
    """
    graph: dict[str, list[str]] = {}
    for step in steps:
        graph[step.id] = list(step.depends_on)
    return graph


def detect_cycles(graph: dict[str, list[str]]) -> None:
    """Detect cycles in the dependency graph using DFS with coloring.

    Uses white (unvisited), gray (in progress), black (complete) coloring.
    When a gray node is revisited, a cycle is found.

    Raises:
        AppError: CYCLE_DETECTED with the cycle path in details.
    """
    white, gray, black = 0, 1, 2
    color: dict[str, int] = {node: white for node in graph}
    parent: dict[str, str | None] = {node: None for node in graph}

    # Build reverse graph: for each node, who depends on it (children)
    children: dict[str, list[str]] = defaultdict(list)
    for node, deps in graph.items():
        for dep in deps:
            children[dep].append(node)

    def dfs(node: str) -> list[str] | None:
        color[node] = gray
        for child in children.get(node, []):
            if color[child] == gray:
                return _reconstruct_cycle(parent, node, child)
            if color[child] == white:
                parent[child] = node
                cycle = dfs(child)
                if cycle:
                    return cycle
        color[node] = black
        return None

    for node in graph:
        if color[node] == white:
            cycle = dfs(node)
            if cycle:
                raise AppError(
                    code="CYCLE_DETECTED",
                    message=(f"Cycle detected in workflow: {' -> '.join(cycle)}"),
                    status_code=400,
                    details=[{"cycle": cycle}],
                )


def _reconstruct_cycle(
    parent: dict[str, str | None],
    from_node: str,
    to_node: str,
) -> list[str]:
    """Reconstruct the cycle path from DFS parent pointers."""
    path = [to_node]
    current = from_node
    while current != to_node:
        path.append(current)
        current = parent.get(current, to_node)  # type: ignore[assignment]
        if current is None:
            break
    path.append(to_node)
    path.reverse()
    return path


def validate_max_depth(graph: dict[str, list[str]]) -> None:
    """Validate that the longest path does not exceed MAX_DEPTH.

    Uses Kahn's algorithm (topological sort) with depth tracking
    to compute the longest path from any root node.

    Raises:
        AppError: MAX_DEPTH_EXCEEDED if depth exceeds limit.
    """
    forward: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {node: 0 for node in graph}

    for node, deps in graph.items():
        in_degree.setdefault(node, 0)
        for dep in deps:
            forward[dep].append(node)
            in_degree[node] = in_degree.get(node, 0) + 1

    queue: list[str] = [n for n, d in in_degree.items() if d == 0]
    depth: dict[str, int] = {n: 0 for n in queue}

    while queue:
        current = queue.pop(0)
        for child in forward.get(current, []):
            new_depth = depth[current] + 1
            depth[child] = max(depth.get(child, 0), new_depth)
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    max_found = max(depth.values()) if depth else 0
    if max_found >= MAX_DEPTH:
        raise AppError(
            code="MAX_DEPTH_EXCEEDED",
            message=(
                f"Workflow depth is {max_found + 1}, "
                f"exceeding the maximum of {MAX_DEPTH}."
            ),
            status_code=400,
            details=[{"max_depth": MAX_DEPTH, "actual_depth": max_found + 1}],
        )
