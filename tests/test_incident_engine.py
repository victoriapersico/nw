from datetime import datetime, timezone

from backend.incidents.engine import IncidentEngine
from backend.schemas import Incident


def make_incident(
    incident_id: str,
    merchant: str = "Rappi",
    country: str = "Brazil",
    severity: str = "high",
    estimated_loss: float = 1_000.0,
    anomaly_score: float = 4.0,
    conversion_drop_pp: float = 20.0,
) -> Incident:
    return Incident(
        incident_id=incident_id,
        merchant=merchant,
        country=country,
        detected_at=datetime(2026, 9, 7, 9, tzinfo=timezone.utc),
        expected_conversion=0.9,
        actual_conversion=0.7,
        conversion_drop_pp=conversion_drop_pp,
        affected_volume=100,
        estimated_loss=estimated_loss,
        estimated_loss_per_hour=estimated_loss * 12,
        severity=severity,
        anomaly_score=anomaly_score,
    )


def test_engine_keeps_independent_incidents_separate() -> None:
    incidents = IncidentEngine().process([
        make_incident("inc-rappi-br", merchant="Rappi", country="Brazil"),
        make_incident("inc-carrefour-mx", merchant="Carrefour", country="Mexico"),
    ])

    assert len(incidents) == 2
    assert {incident.incident_id for incident in incidents} == {
        "inc-rappi-br", "inc-carrefour-mx"
    }


def test_engine_keeps_strongest_exact_duplicate() -> None:
    incidents = IncidentEngine().process([
        make_incident("inc-rappi-br", severity="medium", estimated_loss=500.0, anomaly_score=3.5),
        make_incident("inc-rappi-br", severity="critical", estimated_loss=5_000.0, anomaly_score=8.0),
    ])

    assert len(incidents) == 1
    assert incidents[0].incident_id == "inc-rappi-br"
    assert incidents[0].severity == "critical"


def test_engine_keeps_distinct_incidents_in_same_merchant_country() -> None:
    incidents = IncidentEngine().process([
        make_incident("inc-rappi-br-stripe"),
        make_incident("inc-rappi-br-itau"),
    ])

    assert len(incidents) == 2
    assert {incident.incident_id for incident in incidents} == {
        "inc-rappi-br-stripe", "inc-rappi-br-itau"
    }


def test_engine_prioritizes_severity_before_money_impact() -> None:
    incidents = IncidentEngine().process([
        make_incident("inc-high-expensive", severity="high", estimated_loss=10_000.0, anomaly_score=7.0),
        make_incident("inc-critical-smaller", merchant="Carrefour", country="Mexico", severity="critical", estimated_loss=2_000.0, anomaly_score=5.0),
        make_incident("inc-medium", merchant="Despegar", country="Colombia", severity="medium", estimated_loss=500.0, anomaly_score=4.0),
    ])

    assert [incident.incident_id for incident in incidents] == [
        "inc-critical-smaller", "inc-high-expensive", "inc-medium"
    ]

def test_engine_prioritizes_higher_loss_within_same_severity() -> None:
    incidents = IncidentEngine().process(
        [
            make_incident(
                "inc-high-smaller-loss",
                merchant="Rappi",
                country="Brazil",
                severity="high",
                estimated_loss=2_000.0,
                anomaly_score=8.0,
            ),
            make_incident(
                "inc-high-larger-loss",
                merchant="Carrefour",
                country="Mexico",
                severity="high",
                estimated_loss=9_000.0,
                anomaly_score=4.0,
            ),
        ]
    )

    assert [incident.incident_id for incident in incidents] == [
        "inc-high-larger-loss",
        "inc-high-smaller-loss",
    ]