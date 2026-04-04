from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

# 让测试在未安装包的情况下可直接导入本地源码。
CURRENT_DIR = Path(__file__).resolve()
CLI_SRC_ROOT = CURRENT_DIR.parents[1] / "src"
if str(CLI_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(CLI_SRC_ROOT))

from cli.message_store import AsyncChatStore  # noqa: E402


@pytest.mark.asyncio
async def test_fetch_unread_messages_only_contains_user_messages() -> None:
    store = AsyncChatStore(default_channel="cli")

    await store.send_message(sender="user", text=" 你好 ")
    await store.send_message(sender="ai", text="你好，我看见你了")

    unread = await store.fetch_unread_messages()
    assert len(unread) == 1
    assert unread[0].channel == "cli"
    assert unread[0].sender == "user"
    assert unread[0].text == "你好"
    assert unread[0].message_id == 1

    drained_again = await store.fetch_unread_messages()
    assert drained_again == []


@pytest.mark.asyncio
async def test_fetch_unread_messages_drain_is_atomic_under_concurrency() -> None:
    store = AsyncChatStore(default_channel="cli")
    total = 50

    async def _send(index: int) -> None:
        await store.send_message(sender="user", text=f"msg-{index}")

    await asyncio.gather(*(_send(index) for index in range(total)))

    drained = await store.fetch_unread_messages()
    drained_ids = sorted(item.message_id for item in drained)
    assert len(drained) == total
    assert drained_ids == list(range(1, total + 1))

    assert await store.fetch_unread_messages() == []


@pytest.mark.asyncio
async def test_list_message_history_page_1_returns_newest_messages() -> None:
    store = AsyncChatStore(default_channel="cli")
    for index in range(6):
        sender = "user" if index % 2 == 0 else "ai"
        await store.send_message(sender=sender, text=f"msg-{index + 1}")

    history = await store.list_message_history(page=1, page_size=3)
    assert [item.id for item in history] == [6, 5, 4]
    assert [item.text for item in history] == ["msg-6", "msg-5", "msg-4"]


@pytest.mark.asyncio
async def test_list_message_history_page_2_returns_older_messages() -> None:
    store = AsyncChatStore(default_channel="cli")
    for index in range(6):
        await store.send_message(sender="user", text=f"msg-{index + 1}")

    history = await store.list_message_history(page=2, page_size=2)
    assert [item.id for item in history] == [4, 3]


@pytest.mark.asyncio
async def test_list_message_history_page_out_of_range_returns_empty() -> None:
    store = AsyncChatStore(default_channel="cli")
    for index in range(3):
        await store.send_message(sender="user", text=f"msg-{index + 1}")

    history = await store.list_message_history(page=3, page_size=2)
    assert history == []


@pytest.mark.asyncio
async def test_list_message_history_validates_arguments() -> None:
    store = AsyncChatStore(default_channel="cli")
    await store.send_message(sender="user", text="msg-1")

    with pytest.raises(ValueError, match="page"):
        await store.list_message_history(page=0)
    with pytest.raises(ValueError, match="page_size"):
        await store.list_message_history(page_size=0)
