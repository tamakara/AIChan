from __future__ import annotations

import json
from dataclasses import dataclass, field
from urllib import error, parse, request


class HTTPClientError(RuntimeError):
    """通用 HTTP 客户端异常。"""


@dataclass
class HTTPClient:
    """
    通用同步 HTTP 客户端（JSON 请求/响应）。

    设计目标：
    - 不绑定任何业务语义（如 CLI/Telegram/Discord）。
    - 仅负责基础 HTTP 请求发送与 JSON 解析。
    """

    base_url: str
    timeout_seconds: float = 5.0
    default_headers: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.base_url = self.base_url.rstrip("/")
        if not self.base_url:
            raise ValueError("base_url 不能为空")
        self.default_headers.setdefault("Accept", "application/json")

    def request_json(
        self,
        method: str,
        path: str,
        query: dict[str, object] | None = None,
        payload: object | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        """发送请求并将响应解析为 JSON。"""
        request_headers = dict(self.default_headers)
        if headers:
            request_headers.update(headers)

        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            request_headers.setdefault("Content-Type", "application/json")

        req = request.Request(
            url=self._build_url(path=path, query=query),
            data=body,
            headers=request_headers,
            method=method.upper(),
        )

        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw_text = response.read().decode("utf-8")
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise HTTPClientError(
                f"HTTP 请求失败（{exc.code}）：{detail or exc.reason}"
            ) from exc
        except error.URLError as exc:
            raise HTTPClientError(f"无法连接到服务端：{exc.reason}") from exc

        if not raw_text:
            return {}

        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise HTTPClientError("服务端返回了非 JSON 内容") from exc

    def _build_url(self, path: str, query: dict[str, object] | None = None) -> str:
        normalized_path = path if path.startswith("/") else f"/{path}"
        url = f"{self.base_url}{normalized_path}"
        if query:
            query_string = parse.urlencode(query, doseq=True)
            url = f"{url}?{query_string}"
        return url
