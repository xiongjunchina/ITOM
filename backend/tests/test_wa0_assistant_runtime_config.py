"""WA0 bounded assistant tool-runtime configuration contracts."""

import pytest
from pydantic import ValidationError

from app.core.config import Settings


@pytest.mark.parametrize(
    "overrides",
    [
        {"ai_assistant_tool_timeout_seconds": -1},
        {"ai_assistant_tool_timeout_seconds": 0},
        {"ai_assistant_tool_timeout_seconds": 60.1},
        {"ai_assistant_tool_statement_timeout_ms": -1},
        {"ai_assistant_tool_statement_timeout_ms": 0},
        {"ai_assistant_tool_statement_timeout_ms": 59_001},
        {"ai_assistant_tool_executor_workers": 0},
        {"ai_assistant_tool_executor_workers": 33},
        {"ai_assistant_tool_executor_queue_size": -1},
        {"ai_assistant_tool_executor_queue_size": 257},
    ],
)
def test_assistant_tool_runtime_rejects_unsafe_bounds(overrides):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **overrides)


@pytest.mark.parametrize("statement_timeout_ms", [5_000, 5_001])
def test_statement_timeout_must_be_strictly_shorter_than_tool_deadline(statement_timeout_ms):
    with pytest.raises(ValidationError):
        Settings(
            _env_file=None,
            ai_assistant_tool_timeout_seconds=5,
            ai_assistant_tool_statement_timeout_ms=statement_timeout_ms,
        )


def test_assistant_tool_runtime_accepts_documented_safe_boundaries():
    configured = Settings(
        _env_file=None,
        ai_assistant_tool_timeout_seconds=60,
        ai_assistant_tool_statement_timeout_ms=59_000,
        ai_assistant_tool_executor_workers=32,
        ai_assistant_tool_executor_queue_size=256,
    )

    assert configured.ai_assistant_tool_executor_workers == 32
    assert configured.ai_assistant_tool_executor_queue_size == 256
