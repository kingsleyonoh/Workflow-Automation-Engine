"""Execution orchestrator for workflow runs.

Creates execution and step execution records, walks the DAG in
topological order, executes steps directly (synchronous within
async context), and manages state transitions and context merging.
arq queue dispatch will be added in Phase 2.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import Execution, StepExecution, Workflow
from src.engine.context import get_step_input, merge_step_output
from src.engine.models import StepType
from src.engine.parser import parse_workflow_definition
from src.engine.state import transition_execution, transition_step
from src.lib.logger import get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)


async def start_execution(
    session: AsyncSession,
    workflow: Workflow,
    trigger_data: dict[str, Any],
    tenant_id: uuid.UUID,
) -> Execution:
    """Start a new workflow execution.

    Creates the execution record, step execution records, and
    runs the workflow DAG to completion.

    Args:
        session: Async SQLAlchemy session.
        workflow: The workflow ORM model to execute.
        trigger_data: Trigger payload data.
        tenant_id: The tenant owning this execution.

    Returns:
        The completed (or failed) Execution instance.
    """
    parsed = parse_workflow_definition(
        {
            "name": workflow.name,
            "trigger_type": workflow.trigger_type,
            "steps": workflow.steps,
        }
    )

    # Create execution record
    execution = Execution(
        tenant_id=tenant_id,
        workflow_id=workflow.id,
        status="pending",
        trigger_data=trigger_data,
        context={"trigger": trigger_data, "steps": {}},
    )
    session.add(execution)
    await session.flush()

    # Transition to running
    await transition_execution(session, execution.id, "running")

    # Create step execution records
    step_map: dict[str, StepExecution] = {}
    for step_def in parsed.steps:
        retry_config = step_def.retry
        max_attempts = retry_config.max_attempts if retry_config else 3

        step_exec = StepExecution(
            tenant_id=tenant_id,
            execution_id=execution.id,
            step_id=step_def.id,
            step_type=step_def.type.value,
            status="pending",
            max_attempts=max_attempts,
        )
        session.add(step_exec)
        step_map[step_def.id] = step_exec

    await session.flush()

    # Execute DAG
    await _execute_dag(session, execution, parsed, step_map)

    await session.refresh(execution)
    return execution


async def _execute_dag(
    session: AsyncSession,
    execution: Execution,
    parsed: Any,
    step_map: dict[str, StepExecution],
) -> None:
    """Walk the DAG in topological order, executing each step.

    Args:
        session: Async SQLAlchemy session.
        execution: The execution being run.
        parsed: Parsed WorkflowDefinition.
        step_map: Map of step_id -> StepExecution ORM instance.
    """
    step_defs = {s.id: s for s in parsed.steps}
    order = _topological_sort(parsed.steps)
    skipped_steps: set[str] = set()

    for step_id in order:
        step_def = step_defs[step_id]
        step_exec = step_map[step_id]

        if step_id in skipped_steps:
            await transition_step(session, step_exec.id, "skipped")
            continue

        # Execute the step with retry logic
        success = await _execute_step_with_retry(
            session, execution, step_def, step_exec
        )

        if not success:
            # Step exhausted retries -- mark execution failed
            execution.status = "failed"
            execution.error = f"Step '{step_id}' failed after exhausting retries."
            session.add(execution)
            await session.flush()
            return

        # Handle condition step branching
        if step_def.type == StepType.CONDITION:
            newly_skipped = _resolve_condition_branches(
                session, execution, step_def, step_exec
            )
            skipped_steps.update(newly_skipped)

    # All steps completed/skipped -- mark execution completed
    await transition_execution(session, execution.id, "completed")


async def _execute_step_with_retry(
    session: AsyncSession,
    execution: Execution,
    step_def: Any,
    step_exec: StepExecution,
) -> bool:
    """Execute a step with retry logic.

    Args:
        session: Async SQLAlchemy session.
        execution: The parent execution.
        step_def: Step definition from the parser.
        step_exec: StepExecution ORM instance.

    Returns:
        True if the step completed successfully, False if it
        exhausted retries.
    """
    max_attempts = step_exec.max_attempts
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        step_exec.attempt = attempt
        session.add(step_exec)
        await session.flush()

        # Transition to queued then running
        if step_exec.status == "pending" or step_exec.status == "failed":
            await transition_step(session, step_exec.id, "queued")
        await transition_step(session, step_exec.id, "running")

        try:
            # Get step input from context
            await session.refresh(execution)
            context = execution.context or {}
            step_input = get_step_input(context, step_def.id, step_def.config)

            # Execute the step
            output = await _run_step(step_def, step_input)

            # Success -- transition to completed and merge output
            await transition_step(session, step_exec.id, "completed")
            step_exec.output_data = output
            session.add(step_exec)
            await session.flush()

            await merge_step_output(session, execution.id, step_def.id, output)
            return True

        except (AppError, Exception) as exc:
            error_msg = str(exc)
            await transition_step(session, step_exec.id, "failed", error=error_msg)

            if attempt >= max_attempts:
                logger.warning(
                    "step_retries_exhausted",
                    step_id=step_def.id,
                    execution_id=str(execution.id),
                    attempts=attempt,
                    error=error_msg,
                )
                return False

            logger.info(
                "step_retry",
                step_id=step_def.id,
                execution_id=str(execution.id),
                attempt=attempt,
                max_attempts=max_attempts,
            )

    return False


async def _run_step(step_def: Any, context: dict[str, Any]) -> dict[str, Any]:
    """Dispatch a step to the appropriate executor.

    Uses the step registry from src.queue.tasks to map StepType
    to executor classes. Falls back to empty output for unknown types.

    Args:
        step_def: Step definition from the parser.
        context: Step input context.

    Returns:
        Step output dict.

    Raises:
        AppError: On step execution failure.
    """
    from src.queue.tasks import STEP_REGISTRY

    executor_class = STEP_REGISTRY.get(step_def.type)
    if executor_class is not None:
        executor = executor_class()
        return await executor.execute(step_def.config, context)

    # For unsupported step types, return empty output
    logger.warning(
        "unsupported_step_type",
        step_type=step_def.type.value,
        step_id=step_def.id,
    )
    return {}


def _resolve_condition_branches(
    session: AsyncSession,
    execution: Execution,
    step_def: Any,
    step_exec: StepExecution,
) -> set[str]:
    """Determine which branch steps to skip based on condition result.

    Args:
        session: Async SQLAlchemy session.
        execution: The parent execution.
        step_def: Condition step definition.
        step_exec: Condition StepExecution instance.

    Returns:
        Set of step IDs that should be skipped.
    """
    output = step_exec.output_data or {}

    # ConditionExecutor returns { result: bool, branch: "true"|"false" }
    result_value = output.get("result", False)

    # Handle both bool (from ConditionExecutor) and string (legacy)
    if isinstance(result_value, bool):
        is_truthy = result_value
    else:
        result_str = str(result_value)
        is_truthy = bool(result_str) and result_str.lower() not in (
            "false",
            "0",
            "none",
            "",
        )

    true_branch = step_def.config.get("true_branch", [])
    false_branch = step_def.config.get("false_branch", [])

    if is_truthy:
        return set(false_branch)
    else:
        return set(true_branch)


def _topological_sort(steps: list[Any]) -> list[str]:
    """Sort steps in topological order (respecting depends_on).

    Args:
        steps: List of StepDefinition models.

    Returns:
        List of step IDs in execution order.
    """
    from collections import defaultdict, deque

    graph: dict[str, list[str]] = defaultdict(list)
    in_degree: dict[str, int] = {}

    for step in steps:
        in_degree.setdefault(step.id, 0)
        for dep in step.depends_on:
            graph[dep].append(step.id)
            in_degree[step.id] = in_degree.get(step.id, 0) + 1

    queue: deque[str] = deque()
    for step_id, degree in in_degree.items():
        if degree == 0:
            queue.append(step_id)

    result: list[str] = []
    while queue:
        node = queue.popleft()
        result.append(node)
        for child in graph.get(node, []):
            in_degree[child] -= 1
            if in_degree[child] == 0:
                queue.append(child)

    return result
