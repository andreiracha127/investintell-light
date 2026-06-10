from fastapi import FastAPI

from app.api.routes import health as health_router


def create_app() -> FastAPI:
    application = FastAPI(
        title="Investintell Light API",
        version="0.1.0",
    )
    application.include_router(health_router.router)
    return application


app = create_app()
