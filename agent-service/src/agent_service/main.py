import uvicorn

from .app.app import app
from .app.config import get_settings


def main() -> None:
    settings = get_settings()

    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    main()
