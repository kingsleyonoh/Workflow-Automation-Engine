"""Condition step executor for workflow branching.

Evaluates a Jinja2 expression as a boolean and returns which branch
(true/false) should be executed. The orchestrator uses this result
to skip steps in the non-taken branch.
"""

from typing import Any

from src.lib.expressions import evaluate_expression
from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.steps.base import BaseStepExecutor

logger = get_logger(__name__)

# String values considered falsy for condition evaluation
_FALSY_VALUES = frozenset({"", "false", "0", "none", "False", "None"})


class ConditionExecutor(BaseStepExecutor):
    """Step executor that evaluates conditional expressions.

    Config: ``{ expression, true_branch: [step_ids], false_branch: [step_ids] }``
    Output: ``{ result: bool, branch: "true"|"false", branch_steps: [...] }``

    The orchestrator handles marking non-taken branch steps as skipped.
    """

    async def execute(
        self, config: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluate the condition expression and return branch info.

        Args:
            config: Must contain ``expression`` key. Optionally
                    ``true_branch`` and ``false_branch`` step ID lists.
            context: Execution context for Jinja2 evaluation.

        Returns:
            Dict with ``result`` (bool), ``branch`` ("true"/"false"),
            and ``branch_steps`` (list of step IDs for the taken branch).

        Raises:
            AppError: STEP_CONFIG_ERROR if expression is missing.
            AppError: EXPRESSION_ERROR on Jinja2 evaluation failure.
        """
        if "expression" not in config:
            raise AppError(
                code="STEP_CONFIG_ERROR",
                message="Condition step requires 'expression' in config.",
                status_code=400,
            )

        expression = config["expression"]
        true_branch = config.get("true_branch", [])
        false_branch = config.get("false_branch", [])

        logger.info(
            "condition_evaluate",
            expression=expression[:100] if expression else "",
        )

        result_str = evaluate_expression(expression, context)
        is_truthy = _evaluate_truthiness(result_str)

        if is_truthy:
            return {
                "result": True,
                "branch": "true",
                "branch_steps": true_branch,
            }
        else:
            return {
                "result": False,
                "branch": "false",
                "branch_steps": false_branch,
            }


def _evaluate_truthiness(value: str) -> bool:
    """Determine boolean truthiness of a rendered expression string.

    Non-empty strings that are not "false", "0", or "none" are truthy.

    Args:
        value: The rendered expression string.

    Returns:
        True if the value is considered truthy.
    """
    if not value:
        return False
    return value.strip().lower() not in _FALSY_VALUES
