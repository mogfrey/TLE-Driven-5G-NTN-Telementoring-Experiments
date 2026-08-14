from __future__ import annotations

import argparse
from pathlib import Path

from .orbit import GroundPoint, generate_trace, load_tle_satellites, parse_utc, select_satellite, write_trace_csv
from .provenance import collect_manifest, write_manifest


def _ground_point(lat: float, lon: float, altitude_m: float) -> GroundPoint:
    return GroundPoint(latitude_deg=lat, longitude_deg=lon, altitude_m=altitude_m)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ntn-exp")
    subparsers = parser.add_subparsers(dest="command", required=True)

    provenance = subparsers.add_parser("provenance", help="Capture a run provenance manifest")
    provenance.add_argument("--config", required=True)
    provenance.add_argument("--framework-root", default=".")
    provenance.add_argument("--tle-file")
    provenance.add_argument("--output", required=True)

    trace = subparsers.add_parser("tle-trace", help="Generate a deterministic TLE orbital trace")
    trace.add_argument("--tle-file", required=True)
    trace.add_argument("--satellite", required=True, help="Exact/partial satellite name or NORAD ID")
    trace.add_argument("--start", required=True, help="ISO-8601 timestamp, e.g. 2026-08-14T12:00:00Z")
    trace.add_argument("--duration-s", type=float, required=True)
    trace.add_argument("--step-s", type=float, default=1.0)
    trace.add_argument("--ue-lat", type=float, required=True)
    trace.add_argument("--ue-lon", type=float, required=True)
    trace.add_argument("--ue-alt-m", type=float, default=0.0)
    trace.add_argument("--gateway-lat", type=float)
    trace.add_argument("--gateway-lon", type=float)
    trace.add_argument("--gateway-alt-m", type=float, default=0.0)
    trace.add_argument("--nr-carrier-hz", type=float)
    trace.add_argument("--feeder-carrier-hz", type=float)
    trace.add_argument("--elevation-mask-deg", type=float, default=10.0)
    trace.add_argument("--output", required=True)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "provenance":
        manifest = collect_manifest(
            config_path=args.config,
            framework_root=args.framework_root,
            tle_path=args.tle_file,
        )
        write_manifest(manifest, args.output)
        print(f"wrote provenance manifest: {args.output}")
        return

    if args.command == "tle-trace":
        if (args.gateway_lat is None) != (args.gateway_lon is None):
            parser.error("--gateway-lat and --gateway-lon must be supplied together")

        satellites = load_tle_satellites(args.tle_file)
        satellite = select_satellite(satellites, args.satellite)
        ue = _ground_point(args.ue_lat, args.ue_lon, args.ue_alt_m)
        gateway = None
        if args.gateway_lat is not None:
            gateway = _ground_point(args.gateway_lat, args.gateway_lon, args.gateway_alt_m)

        rows = generate_trace(
            satellite=satellite,
            start_utc=parse_utc(args.start),
            duration_s=args.duration_s,
            step_s=args.step_s,
            ue=ue,
            gateway=gateway,
            nr_carrier_hz=args.nr_carrier_hz,
            feeder_carrier_hz=args.feeder_carrier_hz,
            elevation_mask_deg=args.elevation_mask_deg,
        )
        write_trace_csv(rows, args.output)
        visible = sum(1 for row in rows if row["visible"])
        print(
            f"wrote {len(rows)} samples for {satellite.name} to {Path(args.output)} "
            f"({visible} jointly visible samples)"
        )
        return

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main()
