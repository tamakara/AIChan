import uvicorn

from .app import app
from .config import get_settings
from .logger import configure_logging


def main() -> None:
    settings = get_settings()
    configure_logging()

    uvicorn.run(
        app,
        host=settings.server.host,
        port=settings.server.port,
        log_level="critical",
        access_log=False,
        log_config=None,
    )


if __name__ == "__main__":
    main()
