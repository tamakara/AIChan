from __future__ import annotations

from typing import Any

from .napcat_ws import NapcatWsGateway

FILE_ID_KEYS = ("file_id", "file", "id")
URL_KEYS = ("url", "download_url", "file_url")


class NapcatFileResolver:
    """把 QQ 文件消息里的 file_id 换成 hub 可下载的临时 URL。"""

    def __init__(self, napcat_ws: NapcatWsGateway) -> None:
        self._napcat_ws = napcat_ws

    async def resolve_file_url(
        self,
        *,
        event: dict[str, Any],
        data: dict[str, Any],
    ) -> str | None:
        file_id = _first_str(data, FILE_ID_KEYS)
        if not file_id:
            return None

        # 私聊文件通常需要先通过 NapCat action 换取临时下载 URL；
        # 若当前 NapCat 版本没有该动作，再尝试通用 get_file 的返回数据。
        for action in ("get_private_file_url", "get_file"):
            action_data = await self._call_file_action(action, {"file_id": file_id})
            url = _url_from_action_data(action_data)
            if url:
                return url
        return None

    async def _call_file_action(self, action: str, params: dict[str, Any]) -> object:
        try:
            response = await self._napcat_ws.send_action(action=action, params=params)
        except Exception:
            return None

        if response.get("status") != "ok" or response.get("retcode") not in (0, None):
            return None
        return response.get("data")


def _first_str(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _url_from_action_data(data: object) -> str | None:
    if isinstance(data, str):
        return data if _is_http_url(data) else None

    if not isinstance(data, dict):
        return None

    for key in URL_KEYS:
        value = data.get(key)
        if isinstance(value, str) and _is_http_url(value):
            return value
    return None


def _is_http_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")
