"""Base class for LangChain-compatible tax calculation skills."""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, ClassVar

from pydantic import BaseModel

try:
    from langchain_core.tools import BaseTool as LangChainBaseTool
except ImportError:  # pragma: no cover - local dev fallback when optional package is absent

    class LangChainBaseTool:
        """Small local fallback matching the BaseTool invoke surface used by tests."""

        name: str = ""
        description: str = ""
        args_schema: type[BaseModel] | None = None

        def invoke(self, input_data: dict[str, Any]) -> dict[str, Any]:
            if self.args_schema is None:
                return self._run(**input_data)
            validated = self.args_schema.model_validate(input_data)
            return self._run(**validated.model_dump())


def _plain_value(value: Any) -> Any:
    """Convert Pydantic containers from LangChain validation into engine-friendly values."""

    if isinstance(value, BaseModel):
        return {key: _plain_value(item) for key, item in value.model_dump().items()}
    if isinstance(value, dict):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_plain_value(item) for item in value)
    return value


class TaxSkillResult(BaseModel):
    """Standardized Skill output envelope."""

    status: str
    result: dict[str, Any]
    source_attribution: str
    engine_function: str


class TaxSkill(LangChainBaseTool):
    """Base for tax calculation Skills that delegate all math to engine functions."""

    source_attribution: ClassVar[str] = ""
    engine_function_name: ClassVar[str] = ""
    # Calculation skills are served via the generic /api/skills/{name} route,
    # whose guardrail validates the engine envelope. Extraction-type skills
    # (vision output, not engine truth) set this False and get their own
    # route with their own checks.
    expose_via_api: ClassVar[bool] = True

    def _run(self, **kwargs: Any) -> dict[str, Any]:
        """Call the engine and wrap the result in a standard envelope."""

        engine_result = self._execute_engine(_plain_value(kwargs))
        return TaxSkillResult(
            status=engine_result.get("status", "ok"),
            result=engine_result,
            source_attribution=self.source_attribution,
            engine_function=self.engine_function_name,
        ).model_dump()

    @abstractmethod
    def _execute_engine(self, params: dict[str, Any]) -> dict[str, Any]:
        """Call the underlying engine pure function."""
