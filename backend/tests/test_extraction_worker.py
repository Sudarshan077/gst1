"""Smoke tests for extraction worker CLI."""

from __future__ import annotations

import pytest
from app.extraction import worker


async def test_worker_help_does_not_crash() -> None:
    """python -m app.extraction.worker --help prints usage and exits 0."""
    with pytest.raises(SystemExit) as exc:
        await worker.main(["--help"])
    assert exc.value.code == 0


async def test_worker_no_args_prints_help() -> None:
    result = await worker.main([])
    assert result == 2
