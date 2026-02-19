"""Azure Workshop Management Portal FastAPI 애플리케이션."""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import auth, templates, workshops
from app.config import settings
from app.exceptions import AppError
from app.middleware.auth import AuthMiddleware
from app.utils.logging import configure_logging

configure_logging(log_format=settings.log_format, log_level=settings.log_level)

logger = logging.getLogger(__name__)

# SPA 정적 파일 경로
STATIC_DIR = Path(__file__).parent.parent.parent / "static"

# CORS 허용 오리진: 환경변수에서 콤마 구분 파싱 + 로컬 개발용 기본값
_LOCAL_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:4280",
    "http://localhost:3000",
]
_env_origins = [
    o.strip()
    for o in (settings.allowed_origins or "").split(",")
    if o.strip()
]
_ALLOWED_ORIGINS = list(set(_LOCAL_ORIGINS + _env_origins))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 시작/종료 이벤트를 관리한다."""
    logger.info(
        "Starting %s v%s (subscription: %s)",
        settings.app_name,
        settings.app_version,
        settings.azure_subscription_id,
    )

    yield

    # Gracefully close async Azure SDK sessions to suppress aiohttp warnings
    try:
        from app.services.storage import storage_service
        await storage_service.table_service_client.close()
    except Exception:
        pass

    logger.info("Shutting down application")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="Azure Workshop Management Portal",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api", tags=["Auth"])
app.include_router(workshops.router, prefix="/api", tags=["Workshops"])
app.include_router(templates.router, prefix="/api", tags=["Templates"])


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    """AppError를 일관된 JSON 응답으로 변환하는 글로벌 핸들러."""
    logger.warning(
        "AppError: %s - %s",
        exc.code,
        exc.message,
        extra={
            "path": request.url.path,
            "method": request.method,
            "error_code": exc.code,
            "status_code": exc.status_code,
        },
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.to_dict(),
    )


_INTERNAL_ERROR_RESPONSE = {
    "error": "INTERNAL_ERROR",
    "message": "An unexpected error occurred. Please try again later.",
}


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """예상치 못한 예외를 처리하고 클라이언트에 일반적인 에러 응답을 반환한다."""
    logger.exception(
        "Unhandled exception on %s %s",
        request.method,
        request.url.path,
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content=_INTERNAL_ERROR_RESPONSE)


@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트.

    애플리케이션 상태와 의존 서비스(인증, Table Storage) 연결을 확인한다.
    """
    dependencies: dict = {}

    # Azure credential check
    try:
        from app.services.credential import get_azure_credential

        get_azure_credential()
        dependencies["azure_credential"] = "ok"
    except Exception as e:
        dependencies["azure_credential"] = f"error: {type(e).__name__}"

    # Table Storage connectivity check
    try:
        from app.services.storage import storage_service

        await storage_service.list_all_workshops()
        dependencies["table_storage"] = "ok"
    except Exception as e:
        dependencies["table_storage"] = f"error: {type(e).__name__}"

    all_ok = all(v == "ok" for v in dependencies.values())

    return {
        "status": "healthy" if all_ok else "degraded",
        "app": settings.app_name,
        "version": settings.app_version,
        "dependencies": dependencies,
    }


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")
    
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """비-API 경로에 대해 SPA index.html을 제공한다."""
        file_path = STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(STATIC_DIR / "index.html")


UVICORN_LOG_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "access": {
            "()": "uvicorn.logging.AccessFormatter",
            "fmt": "%(asctime)s - %(levelname)s - %(client_addr)s - \"%(request_line)s\" %(status_code)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
        "default": {
            "fmt": "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "access": {
            "class": "logging.StreamHandler",
            "formatter": "access",
            "stream": "ext://sys.stdout",
        },
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
        },
    },
    "loggers": {
        "uvicorn.access": {
            "handlers": ["access"],
            "level": "INFO",
            "propagate": False,
        },
        "uvicorn.error": {
            "handlers": ["default"],
            "level": "INFO",
            "propagate": False,
        },
    },
}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_config=UVICORN_LOG_CONFIG,
    )

