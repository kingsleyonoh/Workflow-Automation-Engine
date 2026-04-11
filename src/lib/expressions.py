"""Sandboxed Jinja2 expression evaluator for workflow data mapping.

Uses jinja2.sandbox.SandboxedEnvironment to safely evaluate user-provided
template expressions. Supports step output references and trigger payload
access within execution context. NEVER uses default jinja2.Environment.
"""

from typing import Any

from jinja2 import StrictUndefined, TemplateSyntaxError, UndefinedError
from jinja2.sandbox import SandboxedEnvironment, SecurityError

from src.lib.logger import get_logger
from src.lib.utils import AppError

logger = get_logger(__name__)

_env = SandboxedEnvironment(undefined=StrictUndefined)


def evaluate_expression(template: str, context: dict[str, Any]) -> str:
    """Evaluate a Jinja2 template string against the given context.

    Uses a sandboxed environment to prevent SSTI attacks. Supports
    ``{{ steps.step_id.output.field }}`` and ``{{ trigger.payload.field }}``
    syntax for accessing workflow execution data.

    Args:
        template: Jinja2 template string to evaluate.
        context: Dictionary of variables available in the template.

    Returns:
        The rendered string result.

    Raises:
        AppError: EXPRESSION_ERROR on syntax errors, undefined variables,
                  or sandbox security violations.
    """
    if not template:
        return ""

    try:
        compiled = _env.from_string(template)
        return compiled.render(**context)
    except TemplateSyntaxError as exc:
        logger.warning(
            "expression_syntax_error",
            template=template,
            error=str(exc),
        )
        raise AppError(
            code="EXPRESSION_ERROR",
            message=f"Template syntax error: {exc}",
            status_code=400,
        ) from exc
    except UndefinedError as exc:
        logger.warning(
            "expression_undefined_error",
            template=template,
            error=str(exc),
        )
        raise AppError(
            code="EXPRESSION_ERROR",
            message=f"Undefined variable in expression: {exc}",
            status_code=400,
        ) from exc
    except SecurityError as exc:
        logger.warning(
            "expression_security_error",
            template=template,
            error=str(exc),
        )
        raise AppError(
            code="EXPRESSION_ERROR",
            message=f"Unsafe expression blocked: {exc}",
            status_code=400,
        ) from exc
    except Exception as exc:
        logger.error(
            "expression_evaluation_error",
            template=template,
            error=str(exc),
            exc_info=True,
        )
        raise AppError(
            code="EXPRESSION_ERROR",
            message=f"Expression evaluation failed: {exc}",
            status_code=400,
        ) from exc
