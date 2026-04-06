from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, cast

import mcp.types as mcp_types
from mcp.client.session import ClientSession
from pydantic import RootModel

# 固定唤醒通知方法名。
AICHAN_WAKEUP_METHOD = "aichan/wakeup"

# 唤醒事件处理器约定：
# - 第一个参数：来源服务名；
# - 第二个参数：通知参数字典（可能为空）。
WakeupHandler = Callable[[str, dict[str, Any] | None], Awaitable[None]]

# 允许 method 为任意字符串的 custom notification。
_CustomNotificationType = mcp_types.Notification[dict[str, Any] | None, str]


class _ServerNotificationWithCustom(
    RootModel[mcp_types.ServerNotificationType | _CustomNotificationType]
):
    """仅用于替换 SDK 默认通知校验类型。"""

    pass


class MCPClientSession(ClientSession):
    """
    对 `ClientSession` 的最小扩展：
    1. 接受 JSON-RPC custom notifications；
    2. 提供 `on_notification(method)` 注册器。
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        # 先完成父类初始化，确保底层读写流和会话状态可用。
        super().__init__(*args, **kwargs)

        # 保存“方法名 -> 回调列表”的注册表。
        self._custom_notification_handlers: dict[
            str,
            list[Callable[[dict[str, Any] | None], Awaitable[None]]],
        ] = {}

        # 覆盖通知验证模型，允许 method 为任意字符串。
        self._receive_notification_type = cast(Any, _ServerNotificationWithCustom)

    def on_notification(
        self, method: str
    ) -> Callable[
        [Callable[[dict[str, Any] | None], Awaitable[None]]],
        Callable[[dict[str, Any] | None], Awaitable[None]],
    ]:
        """
        注册指定通知方法的异步回调。

        返回值是一个装饰器，便于按 `@session.on_notification("x")` 使用。
        """

        def _decorator(
            func: Callable[[dict[str, Any] | None], Awaitable[None]]
        ) -> Callable[[dict[str, Any] | None], Awaitable[None]]:
            # 同一 method 允许注册多个回调，按注册顺序依次执行。
            self._custom_notification_handlers.setdefault(method, []).append(func)
            return func

        return _decorator

    async def _received_notification(self, notification: Any) -> None:
        # 先执行父类逻辑，保持 SDK 默认行为不变。
        await super()._received_notification(notification)

        # 从通知对象中提取 method，非字符串直接忽略。
        root = getattr(notification, "root", None)
        method = getattr(root, "method", None)
        if not isinstance(method, str):
            return

        # 如果当前 method 没有业务回调，则直接返回。
        handlers = self._custom_notification_handlers.get(method)
        if not handlers:
            return

        # 仅接受 dict|None 两种参数形态，不再做跨版本兼容转换。
        raw_params = getattr(root, "params", None)
        params = raw_params if isinstance(raw_params, dict) else None

        # 逐个回调执行，回调异常交由上层会话链路处理。
        for handler in handlers:
            await handler(params)


def bind_wakeup_notification_handler(
    *,
    session: MCPClientSession,
    server_name: str,
    handler: WakeupHandler,
) -> None:
    """
    绑定 `aichan/wakeup` 处理函数。

    约定：
    - 回调签名固定为 `callback(params: dict | None)`；
    - 不再兼容其他 SDK 变体入参形态。
    """
    @session.on_notification(AICHAN_WAKEUP_METHOD)
    async def _on_wakeup_notification(params: dict[str, Any] | None) -> None:
        await handler(server_name, params)
