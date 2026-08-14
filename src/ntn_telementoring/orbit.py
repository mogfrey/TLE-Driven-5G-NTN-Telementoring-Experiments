from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from skyfield.api import EarthSatellite, load, wgs84

C_M_S = 299_792_458.0


@dataclass(frozen=True)
class GroundPoint:
    latitude_deg: float
    longitude_deg: float
    altitude_m: float = 0.0

    def skyfield_position(self):
        return wgs84.latlon(
            latitude_degrees=self.latitude_deg,
            longitude_degrees=self.longitude_deg,
            elevation_m=self.altitude_m,
        )


def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and return an aware UTC datetime."""
    normalized = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError("Timestamp must include a timezone or Z suffix")
    return dt.astimezone(timezone.utc)


def load_tle_satellites(path: str | Path) -> list[EarthSatellite]:
    satellites = load.tle_file(str(path))
    if not satellites:
        raise ValueError(f"No satellites found in TLE file: {path}")
    return satellites


def select_satellite(satellites: Iterable[EarthSatellite], selector: str) -> EarthSatellite:
    selector_norm = selector.strip().lower()
    exact_name = [s for s in satellites if s.name.lower() == selector_norm]
    if len(exact_name) == 1:
        return exact_name[0]

    satnum_matches = [s for s in satellites if str(s.model.satnum) == selector_norm]
    if len(satnum_matches) == 1:
        return satnum_matches[0]

    partial = [s for s in satellites if selector_norm in s.name.lower()]
    if len(partial) == 1:
        return partial[0]
    if not partial:
        raise ValueError(f"No satellite matches selector: {selector}")
    names = ", ".join(s.name for s in partial[:10])
    raise ValueError(f"Satellite selector is ambiguous: {selector}. Matches: {names}")


def _range_rate_km_s(relative_state) -> float:
    r = relative_state.position.km
    v = relative_state.velocity.km_per_s
    norm = math.sqrt(sum(component * component for component in r))
    if norm == 0:
        return 0.0
    return sum(r_i * v_i for r_i, v_i in zip(r, v)) / norm


def _doppler_hz(carrier_hz: float | None, range_rate_km_s: float) -> float | None:
    if carrier_hz is None:
        return None
    # Positive range rate means the satellite is receding, yielding a negative shift.
    return -carrier_hz * (range_rate_km_s * 1000.0) / C_M_S


def _leg_state(satellite: EarthSatellite, ground_point, t, carrier_hz: float | None) -> dict:
    relative = (satellite - ground_point).at(t)
    altitude, azimuth, distance = relative.altaz()
    range_rate = _range_rate_km_s(relative)
    return {
        "elevation_deg": altitude.degrees,
        "azimuth_deg": azimuth.degrees,
        "slant_range_km": distance.km,
        "range_rate_km_s": range_rate,
        "doppler_hz": _doppler_hz(carrier_hz, range_rate),
    }


def generate_trace(
    *,
    satellite: EarthSatellite,
    start_utc: datetime,
    duration_s: float,
    step_s: float,
    ue: GroundPoint,
    gateway: GroundPoint | None = None,
    nr_carrier_hz: float | None = None,
    feeder_carrier_hz: float | None = None,
    elevation_mask_deg: float = 10.0,
) -> list[dict]:
    """Generate deterministic orbital geometry for one satellite.

    The UE-to-satellite and gateway-to-satellite legs are kept separate. The
    transparent-path propagation delay is computed as the sum of both slant
    ranges. If gateway is omitted, it defaults to the UE ground point; this is
    useful for controlled co-located-ground-endpoint experiments.
    """
    if duration_s <= 0:
        raise ValueError("duration_s must be > 0")
    if step_s <= 0:
        raise ValueError("step_s must be > 0")
    if start_utc.tzinfo is None:
        raise ValueError("start_utc must be timezone-aware")

    gateway = gateway or ue
    ue_sf = ue.skyfield_position()
    gw_sf = gateway.skyfield_position()
    ts = load.timescale()

    rows: list[dict] = []
    count = int(math.floor(duration_s / step_s)) + 1
    for index in range(count):
        dt = start_utc + timedelta(seconds=index * step_s)
        t = ts.from_datetime(dt.astimezone(timezone.utc))
        ue_leg = _leg_state(satellite, ue_sf, t, nr_carrier_hz)
        gw_leg = _leg_state(satellite, gw_sf, t, feeder_carrier_hz)

        transparent_range_km = ue_leg["slant_range_km"] + gw_leg["slant_range_km"]
        propagation_delay_ms = transparent_range_km * 1000.0 / C_M_S * 1000.0
        visible = (
            ue_leg["elevation_deg"] >= elevation_mask_deg
            and gw_leg["elevation_deg"] >= elevation_mask_deg
        )

        geocentric = satellite.at(t)
        rows.append(
            {
                "timestamp_utc": dt.isoformat().replace("+00:00", "Z"),
                "satellite_name": satellite.name,
                "norad_id": int(satellite.model.satnum),
                "visible": visible,
                "elevation_mask_deg": elevation_mask_deg,
                "ue_elevation_deg": ue_leg["elevation_deg"],
                "ue_azimuth_deg": ue_leg["azimuth_deg"],
                "ue_slant_range_km": ue_leg["slant_range_km"],
                "ue_range_rate_km_s": ue_leg["range_rate_km_s"],
                "ue_nr_doppler_hz": ue_leg["doppler_hz"],
                "gateway_elevation_deg": gw_leg["elevation_deg"],
                "gateway_azimuth_deg": gw_leg["azimuth_deg"],
                "gateway_slant_range_km": gw_leg["slant_range_km"],
                "gateway_range_rate_km_s": gw_leg["range_rate_km_s"],
                "gateway_feeder_doppler_hz": gw_leg["doppler_hz"],
                "transparent_path_range_km": transparent_range_km,
                "transparent_one_way_propagation_delay_ms": propagation_delay_ms,
                "sat_gcrs_x_km": geocentric.position.km[0],
                "sat_gcrs_y_km": geocentric.position.km[1],
                "sat_gcrs_z_km": geocentric.position.km[2],
                "sat_gcrs_vx_km_s": geocentric.velocity.km_per_s[0],
                "sat_gcrs_vy_km_s": geocentric.velocity.km_per_s[1],
                "sat_gcrs_vz_km_s": geocentric.velocity.km_per_s[2],
            }
        )
    return rows


def write_trace_csv(rows: list[dict], output: str | Path) -> None:
    if not rows:
        raise ValueError("Cannot write an empty orbital trace")
    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
