"""Incident separation, exact-duplicate removal, and prioritization."""

from backend.incidents.priorization import (
    incident_priority_key,
    prioritize_incidents,
)
from backend.schemas import Incident


def incident_identity(incident: Incident) -> str:
    """Identify an exact incident representation."""
    return incident.incident_id


class IncidentEngine:
    """Prepare detector incidents for RCA and dashboard consumption."""

    def process(self, incidents: list[Incident]) -> list[Incident]:
        """Keep distinct incidents, retain strongest exact duplicates, then
        prioritize."""

        strongest_by_identity: dict[str, Incident] = {}

        for incident in incidents:
            identity = incident_identity(incident)
            current = strongest_by_identity.get(identity)

            if (
                current is None
                or incident_priority_key(incident)
                > incident_priority_key(current)
            ):
                strongest_by_identity[identity] = incident

        return prioritize_incidents(list(strongest_by_identity.values()))
