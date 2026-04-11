"""Transform step executor for Jinja2 data mapping.

Evaluates a Jinja2 expression from the step config against the
execution context. Uses the sandboxed expression evaluator from
src/lib/expressions.py.
"""

from typing import Any

from src.lib.expressions import evaluate_expression
from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.steps.base import BaseStepExecutor

logger = get_logger(__name__)


class TransformExecutor(BaseStepExecutor):
    """Step executor that evaluates Jinja2 expressions.

    Config: ``{ "expression": "{{ trigger.payload.name | upper }}" }``
    Output: ``{ "result": "<evaluated string>" }``
    """

    async def execute(
        self, config: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Evaluate the Jinja2 expression from config against context.

        Args:
            config: Must contain ``expression`` key with Jinja2 template.
            context: Execution context with steps and trigger data.

        Returns:
            Dict with ``result`` key containing the evaluated string.

        Raises:
            AppError: STEP_CONFIG_ERROR if expression key is missing.
            AppError: EXPRESSION_ERROR on Jinja2 evaluation failure.
        """
        if "expression" not in config:
            raise AppError(
                code="STEP_CONFIG_ERROR",
                message="Transform step requires 'expression' in config.",
                status_code=400,
            )

        expression = config["expression"]

        logger.info(
            "transform_execute",
            expression=expression[:100] if expression else "",
        )

        result = evaluate_expression(expression, context)

        return {"result": result}
