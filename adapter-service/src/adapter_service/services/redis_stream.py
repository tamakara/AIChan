from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from redis.asyncio import Redis
from redis.exceptions import ResponseError

from ..config import RedisSettings
from .stream_models import EventStreamMessage


class AdapterRedisStream:
    def __init__(self, settings: RedisSettings) -> None:
        self._settings = settings
        self._client = Redis(
            host=settings.host,
            port=settings.port,
            db=settings.db,
            password=settings.password or None,
            decode_responses=True,
        )

    async def startup(self) -> None:
        await self._client.ping()
        await self._ensure_action_group()

    async def shutdown(self) -> None:
        await self._client.aclose()

    async def publish_event(self, message: EventStreamMessage) -> None:
        await self._client.xadd(self._settings.events_stream, message.to_stream_fields())

    async def read_pending_actions(
        self,
        count: int,
    ) -> list[tuple[str, dict[str, str]]]:
        return await self._read_actions(stream_id="0", count=count, block_ms=None)

    async def read_new_actions(
        self,
        count: int,
    ) -> list[tuple[str, dict[str, str]]]:
        return await self._read_actions(
            stream_id=">",
            count=count,
            block_ms=self._settings.actions_block_ms,
        )

    async def ack_action(self, message_id: str) -> None:
        await self._client.xack(
            self._settings.actions_stream,
            self._settings.actions_group,
            message_id,
        )

    async def _ensure_action_group(self) -> None:
        try:
            await self._client.xgroup_create(
                name=self._settings.actions_stream,
                groupname=self._settings.actions_group,
                id="0",
                mkstream=True,
            )
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def _read_actions(
        self,
        stream_id: str,
        count: int,
        block_ms: int | None,
    ) -> list[tuple[str, dict[str, str]]]:
        result = await self._client.xreadgroup(
            groupname=self._settings.actions_group,
            consumername=self._settings.actions_consumer,
            streams={self._settings.actions_stream: stream_id},
            count=count,
            block=block_ms,
        )
        return _flatten_stream_entries(result)


def _flatten_stream_entries(
    rows: Sequence[tuple[str, Sequence[tuple[str, dict[str, Any]]]]],
) -> list[tuple[str, dict[str, str]]]:
    entries: list[tuple[str, dict[str, str]]] = []
    for _, stream_entries in rows:
        for message_id, fields in stream_entries:
            normalized: dict[str, str] = {}
            for key, value in fields.items():
                normalized[str(key)] = "" if value is None else str(value)
            entries.append((message_id, normalized))
    return entries
