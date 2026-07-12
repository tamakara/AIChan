import uvicorn

from .config import get_settings


def main() -> None:
    settings = get_settings().core
    uvicorn.run("core_service.app:create_app", factory=True, host=settings.host, port=settings.port, log_level=settings.log_level)


if __name__ == "__main__":
    main()
