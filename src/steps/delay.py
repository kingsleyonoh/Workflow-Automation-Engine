"""Delay step executor for timed pauses in workflow execution.

Pauses execution for a configured number of seconds using asyncio.sleep.
Validates that seconds is positive and does not exceed 3600 (1 hour).
"""

import asyncio
from typing import Any

from src.lib.logger import get_logger
from src.lib.utils import AppError
from src.steps.base import BaseStepExecutor

logger = get_logger(__name__)

MAX_DELAY_SECONDS = 3600


class DelayExecutor(BaseStepExecutor):
    """Step executor that pauses for a configured duration.

    Config: ``{ seconds }`` — must be positive, max 3600.
    Output: ``{ "delayed_seconds": N }``
    """

    async def execute(
        self, config: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Pause execution for the configured number of seconds.

        Args:
            config: Must contain ``seconds`` key with a positive number.
            context: Execution context (unused by delay step).

        Returns:
            Dict with ``delayed_seconds`` key.

        Raises:
            AppError: STEP_CONFIG_ERROR if seconds is missing, not a
                      number, zero, negative, or exceeds 3600.
        """
        if "seconds" not in config:
            raise AppError(
                code="STEP_CONFIG_ERROR",
                message="Delay step requires 'seconds' in config.",
                status_code=400,
            )

        seconds = config["seconds"]

        if not isinstance(seconds, (int, float)):
            raise AppError(
                code="STEP_CONFIG_ERROR",
                message="Delay step 'seconds' must be a number.",
                status_code=400,
            )

        if seconds <= 0:
            raise AppError(
                code="STEP_CONFIG_ERROR",
                message="Delay step 'seconds' must be positive.",
                status_code=400,
            )

        if seconds > MAX_DELAY_SECONDS:
            raise AppError(
                code="STEP_CONFIG_ERROR",
                message=(f"Delay step 'seconds' must not exceed {MAX_DELAY_SECONDS}."),
                status_code=400,
            )

        logger.info("delay_execute", seconds=seconds)

        await asyncio.sleep(seconds)

        return {"delayed_seconds": seconds}
