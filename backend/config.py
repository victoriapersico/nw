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


def _read_positive_int(name: str, default: int) -> int:
    raw_value = os.getenv(name, str(default))
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero.")
    return value


def _read_probability(name: str, default: float) -> float:
    raw_value = os.getenv(name, str(default))
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a number.") from exc
    if not 0 <= value <= 1:
        raise RuntimeError(f"{name} must be between 0 and 1.")
    return value


@dataclass(frozen=True)
class Settings:
    openai_api_key: str | None
    openai_model: str
    openai_timeout_seconds: float
    mock_mode: bool
    baseline_minimum_volume: int
    detector_minimum_volume: int
    detector_absolute_drop: float
    detector_z_score_threshold: float
    detector_consecutive_windows: int
    live_window_minutes: int

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
            baseline_minimum_volume=_read_positive_int(
                "BASELINE_MINIMUM_VOLUME", 50
            ),
            detector_minimum_volume=_read_positive_int(
                "DETECTOR_MINIMUM_VOLUME", 50
            ),
            detector_absolute_drop=_read_probability(
                "DETECTOR_ABSOLUTE_DROP", 0.08
            ),
            detector_z_score_threshold=float(
                os.getenv("DETECTOR_Z_SCORE_THRESHOLD", "-3")
            ),
            detector_consecutive_windows=_read_positive_int(
                "DETECTOR_CONSECUTIVE_WINDOWS", 2
            ),
            live_window_minutes=_read_positive_int("LIVE_WINDOW_MINUTES", 5),
        )


settings = Settings.from_environment()
