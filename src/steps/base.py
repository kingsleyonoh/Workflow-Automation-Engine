"""Abstract base class for all step executors.

Defines the interface that every step type executor must implement.
Each step executor takes config and context, executes the step logic,
and returns output data.
"""

from abc import ABC, abstractmethod
from typing import Any


class BaseStepExecutor(ABC):
    """Abstract base for workflow step executors.

    All step type executors (http, transform, condition, delay,
    sub_workflow) must inherit from this class and implement the
    execute method.
    """

    @abstractmethod
    async def execute(
        self, config: dict[str, Any], context: dict[str, Any]
    ) -> dict[str, Any]:
        """Execute the step with the given config and context.

        Args:
            config: Step configuration dict from the workflow definition.
            context: Execution context with steps outputs and trigger data.

        Returns:
            Output dict to be merged into the execution context.

        Raises:
            AppError: On step execution failure.
        """
