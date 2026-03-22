from __future__ import annotations

import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REQUEST_TIMEOUT_SECONDS = 60


def send_message(host: str, port: int, content: str) -> str:
    """
    向 AIChan 服务端发送一条聊天消息，并返回模型回复文本。

    参数：
    - host: 服务端地址
    - port: 服务端端口
    - content: 用户输入内容
    """
    payload = {
        "channel": "cli",
        "content": content,
    }
    req = Request(
        f"http://{host}:{port}/chat",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
        raw = resp.read().decode("utf-8")
        data = json.loads(raw or "{}")
        if "reply" not in data:
            raise RuntimeError(data.get("error") or data.get("detail") or "服务端响应格式不正确")
        return str(data["reply"])


def format_http_error(exc: HTTPError) -> str:
    """将 HTTP 错误转换成更可读的提示文本。"""
    try:
        raw = exc.read().decode("utf-8")
    except Exception:
        raw = ""

    if not raw:
        return f"HTTP {exc.code}"

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return f"HTTP {exc.code}: {raw}"

    detail = data.get("detail") or data.get("error")
    if detail:
        return f"HTTP {exc.code}: {detail}"
    return f"HTTP {exc.code}"


def print_intro(host: str, port: int) -> None:
    line = "=" * 64
    print(line)
    print("AIChan CLI")
    print(f"服务端  : http://{host}:{port}")
    print("提示    : 输入消息后回车发送，按 Ctrl+C 退出")
    print(line)


def print_reply(reply: str, elapsed_seconds: float) -> None:
    content = reply.strip()
    if not content:
        print("AIChan > （空回复）")
    elif "\n" not in content:
        print(f"AIChan > {content}")
    else:
        print("AIChan >")
        for line in content.splitlines():
            print(f"  {line}")
    print(f"[耗时 {elapsed_seconds:.1f}s]")


def main() -> None:
    """
    独立 CLI 客户端入口。

    该进程只负责交互输入输出，不直接依赖 synapse/brain，
    所有请求都通过 HTTP 发给服务端。
    """
    host = (os.getenv("CHAT_SERVER_HOST") or "127.0.0.1").strip() or "127.0.0.1"
    port_raw = os.getenv("CHAT_SERVER_PORT", "8765")

    try:
        port = int(port_raw)
    except ValueError:
        port = 8765
        print("CHAT_SERVER_PORT 配置无效，已回退到默认端口 8765。")

    print_intro(host=host, port=port)
    while True:
        try:
            text = input("\n你 > ").strip()
        except KeyboardInterrupt:
            print("\n\n已退出 AIChan CLI。")
            break
        except EOFError:
            print("\n\n输入流已结束，AIChan CLI 已退出。")
            break

        if not text:
            # 空输入直接忽略，避免产生无意义请求。
            print("AIChan > 请输入内容后再发送。")
            continue

        print("AIChan 思考中...")
        started_at = time.perf_counter()
        try:
            reply = send_message(host=host, port=port, content=text)
        except KeyboardInterrupt:
            print("\n\n请求已中断，AIChan CLI 已退出。")
            break
        except HTTPError as exc:
            print(f"AIChan > 请求失败：{format_http_error(exc)}")
            continue
        except URLError:
            print("AIChan > 无法连接服务端，请先启动 `uv run python main.py`")
            continue
        except Exception as exc:
            # 兜底异常处理，避免客户端在单次失败后退出。
            print(f"AIChan > 请求失败：{exc}")
            continue

        elapsed_seconds = time.perf_counter() - started_at
        print_reply(reply=reply, elapsed_seconds=elapsed_seconds)


if __name__ == "__main__":
    main()
