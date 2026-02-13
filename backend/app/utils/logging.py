"""구조화된 JSON 로깅 포매터.

LOG_FORMAT=json 환경변수 설정 시 모든 로그를 JSON 형식으로 출력한다.
Azure Monitor, ELK 등 로그 수집 시스템과의 연동을 용이하게 한다.
"""
import json
import logging
import traceback
from datetime import UTC, datetime


class JsonFormatter(logging.Formatter):
    """로그 레코드를 JSON 문자열로 포매팅하는 포매터.

    프로덕션 환경에서 구조화된 로깅을 지원하며,
    Azure Monitor 등 외부 시스템에서의 검색/분석을 용이하게 한다.
    """

    def format(self, record: logging.LogRecord) -> str:
        """로그 레코드를 JSON 문자열로 변환한다."""
        log_entry: dict = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        if record.exc_info and record.exc_info[0] is not None:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__,
                "message": str(record.exc_info[1]),
                "traceback": traceback.format_exception(*record.exc_info),
            }

        # extra 필드 병합 (logging.warning("...", extra={...}))
        _SKIP_FIELDS = frozenset({
            "name", "msg", "args", "created", "relativeCreated",
            "exc_info", "exc_text", "stack_info", "lineno", "funcName",
            "filename", "module", "pathname", "thread", "threadName",
            "process", "processName", "levelname", "levelno", "msecs",
            "message", "taskName",
        })
        for key, value in record.__dict__.items():
            if key not in _SKIP_FIELDS and not key.startswith("_"):
                log_entry[key] = value

        return json.dumps(log_entry, ensure_ascii=False, default=str)


def configure_logging(log_format: str = "text", log_level: str = "INFO") -> None:
    """애플리케이션 로깅을 설정한다.

    Args:
        log_format: 로그 형식. "json" 또는 "text".
        log_level: 로그 레벨. 기본값 "INFO".
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level.upper(), logging.INFO))

    # 기존 핸들러 제거
    root_logger.handlers.clear()

    handler = logging.StreamHandler()

    if log_format == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        )

    root_logger.addHandler(handler)

    # Azure SDK 로그 노이즈 억제
    logging.getLogger(
        "azure.core.pipeline.policies.http_logging_policy"
    ).setLevel(logging.WARNING)
    logging.getLogger("azure.identity").setLevel(logging.WARNING)
