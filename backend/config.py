"""Environment-based application settings."""

from dataclasses import dataclass
import os

from dotenv import load_dotenv


load_dotenv()

TRUE_VALUES = {"1", "true", "yes", "on"}


def _read_timeout() -> float:
    raw_value = os.getenv("OPENAI_TIMEOUT_SECONDS", "30")
    try:
        timeout = float(raw_value)
    except ValueError as exc:
        raise RuntimeError("OPENAI_TIMEOUT_SECONDS must be a number.") from exc

    if timeout <= 0:
        raise RuntimeError("OPENAI_TIMEOUT_SECONDS must be greater than zero.")
    return timeout


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    openai_timeout_seconds: float
    mock_mode: bool

    @classmethod
    def from_environment(cls) -> "Settings":
        api_key = os.getenv("OPENAI_API_KEY", "").strip() or None
        force_mock = os.getenv("MOCK_MODE", "false").strip().lower() in TRUE_VALUES

        return cls(
            openai_api_key=api_key,
            openai_model=os.getenv("OPENAI_MODEL", "gpt-5-mini").strip()
            or "gpt-5-mini",
            openai_timeout_seconds=_read_timeout(),
            mock_mode=force_mock or api_key is None,
        )


settings = Settings.from_environment()
