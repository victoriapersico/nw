"""Configuration for the interpretable anomaly detector."""

from dataclasses import dataclass


@dataclass(frozen=True)
class DetectorConfig:
    """Thresholds used to decide whether a conversion drop is an incident."""

    minimum_volume: int = 50
    minimum_absolute_drop: float = 0.08
    z_score_threshold: float = -3.0
    consecutive_windows: int = 2

    def __post_init__(self) -> None:
        if self.minimum_volume <= 0:
            raise ValueError("minimum_volume must be greater than zero")

        if not 0 < self.minimum_absolute_drop <= 1:
            raise ValueError(
                "minimum_absolute_drop must be greater than 0 and at most 1"
            )

        if self.z_score_threshold >= 0:
            raise ValueError("z_score_threshold must be negative")

        if self.consecutive_windows <= 0:
            raise ValueError("consecutive_windows must be greater than zero")