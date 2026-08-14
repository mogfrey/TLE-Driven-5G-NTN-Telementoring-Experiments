from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Iterable

from skyfield.api import EarthSatellite, load

from .orbit import GroundPoint


@dataclass(frozen=True)
class PassCandidate:
    satellite_name: str
    norad_id: int
    rise_utc: str
    culmination_utc: str
    set_utc: str
    max_elevation_deg: float


def _iso_utc(t) -> str:
    dt = t.utc_datetime().replace(tzinfo=timezone.utc)
    return dt.isoformat().replace("+00:00", "Z")


def find_visible_passes(
    satellites: Iterable[EarthSatellite],
    *,
    observer: GroundPoint,
    start_utc: datetime,
    end_utc: datetime,
    elevation_mask_deg: float = 10.0,
) -> list[PassCandidate]:
    """Find complete rise/culmination/set passes above an elevation mask."""
    if start_utc.tzinfo is None or end_utc.tzinfo is None:
        raise ValueError("start_utc and end_utc must be timezone-aware")
    if end_utc <= start_utc:
        raise ValueError("end_utc must be after start_utc")

    observer_sf = observer.skyfield_position()
    ts = load.timescale()
    t0 = ts.from_datetime(start_utc.astimezone(timezone.utc))
    t1 = ts.from_datetime(end_utc.astimezone(timezone.utc))
    passes: list[PassCandidate] = []

    for satellite in satellites:
        times, events = satellite.find_events(
            observer_sf,
            t0,
            t1,
            altitude_degrees=elevation_mask_deg,
        )
        current: dict | None = None
        for t, event in zip(times, events):
            event = int(event)
            if event == 0:  # rise
                current = {"rise": t}
            elif event == 1 and current is not None:  # culmination
                altitude, _, _ = (satellite - observer_sf).at(t).altaz()
                current["culmination"] = t
                current["max_elevation_deg"] = altitude.degrees
            elif event == 2 and current is not None:  # set
                current["set"] = t
                if "culmination" in current:
                    passes.append(
                        PassCandidate(
                            satellite_name=satellite.name,
                            norad_id=int(satellite.model.satnum),
                            rise_utc=_iso_utc(current["rise"]),
                            culmination_utc=_iso_utc(current["culmination"]),
                            set_utc=_iso_utc(current["set"]),
                            max_elevation_deg=float(current["max_elevation_deg"]),
                        )
                    )
                current = None

    passes.sort(key=lambda item: item.rise_utc)
    return passes


def select_geometry_bands(passes: list[PassCandidate]) -> dict[str, PassCandidate]:
    """Select the first chronological pass in the predeclared geometry bands."""
    bands = {
        "high": lambda elevation: elevation >= 75.0,
        "medium": lambda elevation: 40.0 <= elevation <= 60.0,
        "low": lambda elevation: 20.0 <= elevation <= 30.0,
    }
    selected: dict[str, PassCandidate] = {}
    used: set[tuple[str, str]] = set()

    for label, predicate in bands.items():
        for candidate in passes:
            key = (candidate.satellite_name, candidate.rise_utc)
            if key in used:
                continue
            if predicate(candidate.max_elevation_deg):
                selected[label] = candidate
                used.add(key)
                break
    return selected


def pass_to_dict(candidate: PassCandidate) -> dict:
    return asdict(candidate)
