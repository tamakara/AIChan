import asyncio

from hub_service.services.napcat_file_resolver import NapcatFileResolver


class StubNapcatWs:
    def __init__(self, responses: list[dict]) -> None:
        self.responses = responses
        self.actions: list[tuple[str, dict]] = []

    async def send_action(self, action: str, params: dict) -> dict:
        self.actions.append((action, params))
        return self.responses.pop(0)


def test_resolve_file_url_uses_private_file_action() -> None:
    napcat_ws = StubNapcatWs(
        [{"status": "ok", "retcode": 0, "data": {"url": "https://download"}}]
    )
    resolver = NapcatFileResolver(napcat_ws)  # type: ignore[arg-type]

    url = asyncio.run(
        resolver.resolve_file_url(
            event={"message_type": "private"},
            data={"file_id": "file-1", "name": "a.txt"},
        )
    )

    assert url == "https://download"
    assert napcat_ws.actions == [("get_private_file_url", {"file_id": "file-1"})]


def test_resolve_file_url_falls_back_to_get_file() -> None:
    napcat_ws = StubNapcatWs(
        [
            {"status": "failed", "retcode": 1400, "data": None},
            {"status": "ok", "retcode": 0, "data": {"download_url": "https://fallback"}},
        ]
    )
    resolver = NapcatFileResolver(napcat_ws)  # type: ignore[arg-type]

    url = asyncio.run(
        resolver.resolve_file_url(
            event={"message_type": "private"},
            data={"file": "file-1"},
        )
    )

    assert url == "https://fallback"
    assert napcat_ws.actions == [
        ("get_private_file_url", {"file_id": "file-1"}),
        ("get_file", {"file_id": "file-1"}),
    ]
