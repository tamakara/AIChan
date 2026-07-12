import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run("aichan_qq_adapter.app:app", host=settings.server.host, port=settings.server.port)
