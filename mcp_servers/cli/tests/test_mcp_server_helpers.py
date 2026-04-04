from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 让测试在未安装包的情况下可直接导入本地源码。
CURRENT_DIR = Path(__file__).resolve()
CLI_SRC_ROOT = CURRENT_DIR.parents[1] / "src"
if str(CLI_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(CLI_SRC_ROOT))

from cli.mcp_server import _read_int_argument  # noqa: E402


def test_read_int_argument_returns_default_when_missing() -> None:
    assert _read_int_argument({}, "page_size", minimum=1, default=50) == 50


def test_read_int_argument_returns_default_when_null() -> None:
    assert _read_int_argument({"page_size": None}, "page_size", minimum=1, default=50) == 50


def test_read_int_argument_rejects_non_integer_type() -> None:
    with pytest.raises(ValueError, match="page_size"):
        _read_int_argument({"page_size": "10"}, "page_size", minimum=1)


def test_read_int_argument_rejects_bool_value() -> None:
    with pytest.raises(ValueError, match="page_size"):
        _read_int_argument({"page_size": True}, "page_size", minimum=1)


def test_read_int_argument_enforces_minimum_and_maximum() -> None:
    with pytest.raises(ValueError, match="page"):
        _read_int_argument({"page": 0}, "page", minimum=1)

    with pytest.raises(ValueError, match="page_size"):
        _read_int_argument({"page_size": 300}, "page_size", minimum=1, maximum=200)

    assert _read_int_argument(
        {"page_size": 120}, "page_size", minimum=1, maximum=200
    ) == 120
