#!/usr/bin/env python3
"""Portable synthetic multimodal benchmark for NTN continuity experiments.

Host-neutral revision of the Málaga synthetic telementoring workload. It keeps
the same audio/video/control traffic model while recording sender and receiver
state required for continuity-aware reconciliation.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import socket
import statistics
import struct
import threading
import time
from pathlib import Path
from typing import Any

DSCP = {"audio": 0x88, "video": 0x80, "control": 0xB8}
PORT_OFFSETS = {"audio": 1, "video": 2, "control": 3}


def wall_time_ns() -> int:
    return time.time_ns()


def monotonic_s() -> float:
    return time.monotonic()


def iso_utc_from_ns(value: int | None) -> str | None:
    if value is None:
        return None
    seconds = value / 1_000_000_000
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(seconds)) + f".{value % 1_000_000_000:09d}Z"


def make_header(
    flow: str,
    seq: int,
    tx_time_ns: int,
    frame_id: int = -1,
    frame_type: str = "N",
    pkt_in_frame: int = 0,
    pkts_in_frame: int = 1,
) -> bytes:
    return (
        f"{flow},{seq},{tx_time_ns},{frame_id},{frame_type},{pkt_in_frame},{pkts_in_frame},"
    ).encode("ascii")


def configure_socket(sock: socket.socket, bind_ip: str | None, dscp: int | None) -> None:
    if bind_ip:
        sock.bind((bind_ip, 0))
    if dscp is not None:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_TOS, dscp)


def new_sender_stats(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "units_generated": 0,
        "socket_send_successes": 0,
        "socket_send_errors": 0,
        "first_generated_seq": None,
        "last_generated_seq": None,
        "first_send_time_ns": None,
        "last_send_time_ns": None,
        "first_send_time_utc": None,
        "last_send_time_utc": None,
        "last_send_error": None,
    }


def send_datagram(
    sock: socket.socket,
    packet: bytes,
    destination: tuple[str, int],
    seq: int,
    stats: dict[str, Any],
) -> None:
    event_ns = wall_time_ns()
    if stats["first_send_time_ns"] is None:
        stats["first_send_time_ns"] = event_ns
        stats["first_send_time_utc"] = iso_utc_from_ns(event_ns)
    stats["last_send_time_ns"] = event_ns
    stats["last_send_time_utc"] = iso_utc_from_ns(event_ns)
    stats["units_generated"] += 1
    if stats["first_generated_seq"] is None:
        stats["first_generated_seq"] = seq
    stats["last_generated_seq"] = seq
    try:
        sock.sendto(packet, destination)
        stats["socket_send_successes"] += 1
    except OSError as exc:
        stats["socket_send_errors"] += 1
        stats["last_send_error"] = f"{type(exc).__name__}: {exc}"


def pace_until(target: float) -> None:
    remaining = target - monotonic_s()
    if remaining > 0:
        time.sleep(remaining)


def send_audio(
    server_ip: str,
    port: int,
    duration_s: float,
    results: dict[str, Any],
    seed: int,
    bind_ip: str | None,
    qos: bool,
    interval_ms: float,
) -> None:
    rng = random.Random(seed + 100)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    configure_socket(sock, bind_ip, DSCP["audio"] if qos else None)
    stats = new_sender_stats(f"Opus-like audio: {interval_ms:g} ms interval, 60-120 byte payload")
    stats["nominal_interval_ms"] = interval_ms
    seq = 0
    start = monotonic_s()
    deadline = start + duration_s
    interval_s = interval_ms / 1000.0
    next_send = start
    while monotonic_s() < deadline:
        tx_ns = wall_time_ns()
        payload = b"A" * rng.randint(60, 120)
        send_datagram(sock, make_header("audio", seq, tx_ns) + payload, (server_ip, port), seq, stats)
        seq += 1
        next_send += interval_s
        pace_until(next_send)
    sock.close()
    results["audio"] = stats


def send_control(
    server_ip: str,
    port: int,
    duration_s: float,
    results: dict[str, Any],
    seed: int,
    bind_ip: str | None,
    qos: bool,
    rate_hz: float,
) -> None:
    rng = random.Random(seed + 200)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    configure_socket(sock, bind_ip, DSCP["control"] if qos else None)
    stats = new_sender_stats("Synthetic control: position, velocity, force, button state")
    stats["rate_hz"] = rate_hz
    interval_s = 1.0 / rate_hz
    seq = 0
    start = monotonic_s()
    deadline = start + duration_s
    next_send = start
    while monotonic_s() < deadline:
        tx_ns = wall_time_ns()
        position = [rng.uniform(-1, 1) for _ in range(3)]
        velocity = [rng.uniform(-0.2, 0.2) for _ in range(3)]
        force = [rng.uniform(0, 5) for _ in range(3)]
        button_state = rng.randint(0, 1)
        payload = struct.pack("!9fB", *(position + velocity + force), button_state)
        send_datagram(sock, make_header("control", seq, tx_ns) + payload, (server_ip, port), seq, stats)
        seq += 1
        next_send += interval_s
        pace_until(next_send)
    sock.close()
    results["control"] = stats


def send_video(
    server_ip: str,
    port: int,
    duration_s: float,
    results: dict[str, Any],
    seed: int,
    bind_ip: str | None,
    qos: bool,
    fps: float,
) -> None:
    rng = random.Random(seed + 300)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    configure_socket(sock, bind_ip, DSCP["video"] if qos else None)
    stats = new_sender_stats("H.264/H.265-like video: GOP=30, I/P frames, 1000-byte packetization")
    stats.update({"fps": fps, "frames_generated": 0, "first_frame_id": None, "last_frame_id": None})
    seq = 0
    frame_id = 0
    frame_interval_s = 1.0 / fps
    mtu_payload = 1000
    start = monotonic_s()
    deadline = start + duration_s
    next_frame = start
    while monotonic_s() < deadline:
        if frame_id % 30 == 0:
            frame_type = "I"
            frame_size = rng.randint(12000, 22000)
        else:
            frame_type = "P"
            frame_size = rng.randint(1200, 4500)
        packets_in_frame = math.ceil(frame_size / mtu_payload)
        if stats["first_frame_id"] is None:
            stats["first_frame_id"] = frame_id
        stats["last_frame_id"] = frame_id
        stats["frames_generated"] += 1
        for packet_index in range(packets_in_frame):
            tx_ns = wall_time_ns()
            chunk_size = min(mtu_payload, frame_size - packet_index * mtu_payload)
            packet = make_header(
                "video", seq, tx_ns, frame_id, frame_type, packet_index, packets_in_frame
            ) + b"V" * chunk_size
            send_datagram(sock, packet, (server_ip, port), seq, stats)
            seq += 1
            time.sleep(0.001)
        frame_id += 1
        next_frame += frame_interval_s
        pace_until(next_frame)
    sock.close()
    results["video"] = stats


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = (len(ordered) - 1) * q
    lo = math.floor(index)
    hi = math.ceil(index)
    if lo == hi:
        return ordered[lo]
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)


def receive_flow(
    flow_name: str,
    port: int,
    duration_s: float,
    results: dict[str, Any],
    bind_ip: str,
    deadline_ms: float | None,
    record_one_way_delay: bool,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((bind_ip, port))
    sock.settimeout(0.5)
    end_monotonic = monotonic_s() + duration_s
    packets_received = 0
    bytes_received = 0
    sequences: set[int] = set()
    arrivals: list[float] = []
    owd_ms: list[float] = []
    first_rx_ns = None
    last_rx_ns = None
    first_seq = None
    max_seq = None
    video_frames: dict[int, dict[str, Any]] = {}
    parse_errors = 0

    while monotonic_s() < end_monotonic:
        try:
            data, _ = sock.recvfrom(65535)
        except socket.timeout:
            continue
        except OSError:
            break
        rx_ns = wall_time_ns()
        packets_received += 1
        bytes_received += len(data)
        arrivals.append(monotonic_s())
        first_rx_ns = rx_ns if first_rx_ns is None else first_rx_ns
        last_rx_ns = rx_ns
        try:
            parts = data.split(b",", 7)
            seq = int(parts[1])
            tx_ns = int(parts[2])
            frame_id = int(parts[3])
            frame_type = parts[4].decode("ascii")
            pkt_in_frame = int(parts[5])
            pkts_in_frame = int(parts[6])
        except (IndexError, ValueError, UnicodeDecodeError):
            parse_errors += 1
            continue
        sequences.add(seq)
        first_seq = seq if first_seq is None else min(first_seq, seq)
        max_seq = seq if max_seq is None else max(max_seq, seq)
        if record_one_way_delay:
            owd_ms.append((rx_ns - tx_ns) / 1_000_000.0)
        if flow_name == "video":
            frame = video_frames.setdefault(
                frame_id, {"type": frame_type, "pkts_expected": pkts_in_frame, "pkts_rx": set()}
            )
            frame["pkts_rx"].add(pkt_in_frame)
    sock.close()

    unique_received = len(sequences)
    prefix_expected = max_seq + 1 if max_seq is not None else 0
    prefix_missing = max(prefix_expected - unique_received, 0)
    inter_arrival_ms = [
        (arrivals[i] - arrivals[i - 1]) * 1000.0 for i in range(1, len(arrivals))
    ]

    complete_frames = incomplete_iframes = incomplete_pframes = highest_frame_id = None
    if flow_name == "video":
        complete_frames = incomplete_iframes = incomplete_pframes = 0
        highest_frame_id = max(video_frames) if video_frames else None
        for frame in video_frames.values():
            missing = frame["pkts_expected"] - len(frame["pkts_rx"])
            if missing == 0:
                complete_frames += 1
            elif frame["type"] == "I":
                incomplete_iframes += 1
            else:
                incomplete_pframes += 1

    deadline_misses = None
    if deadline_ms is not None and record_one_way_delay:
        deadline_misses = sum(delay > deadline_ms for delay in owd_ms)

    prefix_loss_percent = 100.0 * prefix_missing / prefix_expected if prefix_expected else None
    results[flow_name] = {
        "packets_received": packets_received,
        "unique_sequences_received": unique_received,
        "first_sequence_received": first_seq,
        "highest_sequence_received": max_seq,
        "prefix_expected_packets": prefix_expected,
        "prefix_missing_packets": prefix_missing,
        "prefix_loss_fraction": prefix_missing / prefix_expected if prefix_expected else None,
        "prefix_loss_percent": prefix_loss_percent,
        "expected_packets": prefix_expected,
        "estimated_lost_packets": prefix_missing,
        "estimated_loss_percent": prefix_loss_percent,
        "bytes_received": bytes_received,
        "throughput_kbps": bytes_received * 8.0 / duration_s / 1000.0,
        "first_receive_time_ns": first_rx_ns,
        "last_receive_time_ns": last_rx_ns,
        "first_receive_time_utc": iso_utc_from_ns(first_rx_ns),
        "last_receive_time_utc": iso_utc_from_ns(last_rx_ns),
        "parse_errors": parse_errors,
        "iat_stdev_ms": statistics.stdev(inter_arrival_ms) if len(inter_arrival_ms) > 1 else None,
        "one_way_delay_recorded": record_one_way_delay,
        "one_way_delay_note": (
            "Only interpretable when sender/receiver clock synchronization is independently validated."
            if record_one_way_delay
            else "Not computed; continuity validation does not require synchronized clocks."
        ),
        "mean_one_way_delay_ms": statistics.mean(owd_ms) if owd_ms else None,
        "p95_one_way_delay_ms": percentile(owd_ms, 0.95),
        "deadline_ms": deadline_ms,
        "deadline_misses": deadline_misses,
        "video_highest_frame_id_seen": highest_frame_id,
        "video_frames_seen": len(video_frames) if flow_name == "video" else None,
        "video_complete_frames": complete_frames,
        "video_iframe_incomplete_events": incomplete_iframes,
        "video_pframe_incomplete_events": incomplete_pframes,
    }


def selected_flows(workload: str) -> list[str]:
    return ["audio", "video", "control"] if workload == "combined" else [workload]


def ports(port_base: int) -> dict[str, int]:
    return {name: port_base + offset for name, offset in PORT_OFFSETS.items()}


def run_server(args: argparse.Namespace) -> None:
    port_map = ports(args.port_base)
    deadlines = {
        "audio": args.audio_deadline_ms,
        "video": args.video_deadline_ms,
        "control": args.control_deadline_ms,
    }
    results: dict[str, Any] = {
        "schema_version": 2,
        "benchmark": "ntn-continuity-multimodal",
        "mode": "server",
        "run_id": args.run_id,
        "direction": args.direction,
        "duration_s": args.duration,
        "workload": args.workload,
        "bind_ip": args.bind_ip,
        "ports": port_map,
        "flows": {},
    }
    threads = []
    for flow in selected_flows(args.workload):
        thread = threading.Thread(
            target=receive_flow,
            args=(
                flow,
                port_map[flow],
                args.duration,
                results["flows"],
                args.bind_ip,
                deadlines[flow],
                args.record_one_way_delay,
            ),
        )
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


def run_client(args: argparse.Namespace) -> None:
    port_map = ports(args.port_base)
    results: dict[str, Any] = {
        "schema_version": 2,
        "benchmark": "ntn-continuity-multimodal",
        "mode": "client",
        "run_id": args.run_id,
        "direction": args.direction,
        "server": args.server,
        "bind_ip": args.bind_ip,
        "duration_s": args.duration,
        "workload": args.workload,
        "seed": args.seed,
        "qos_dscp_enabled": args.qos,
        "ports": port_map,
        "flows": {},
    }
    threads = []
    for flow in selected_flows(args.workload):
        if flow == "audio":
            target = send_audio
            fn_args = (
                args.server, port_map[flow], args.duration, results["flows"], args.seed,
                args.bind_ip, args.qos, args.audio_interval_ms,
            )
        elif flow == "video":
            target = send_video
            fn_args = (
                args.server, port_map[flow], args.duration, results["flows"], args.seed,
                args.bind_ip, args.qos, args.video_fps,
            )
        else:
            target = send_control
            fn_args = (
                args.server, port_map[flow], args.duration, results["flows"], args.seed,
                args.bind_ip, args.qos, args.control_rate,
            )
        thread = threading.Thread(target=target, args=fn_args)
        thread.start()
        threads.append(thread)
    for thread in threads:
        thread.join()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Portable multimodal NTN continuity benchmark")
    parser.add_argument("--mode", choices=["server", "client"], required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--duration", type=float, required=True)
    parser.add_argument("--workload", choices=["audio", "video", "control", "combined"], default="combined")
    parser.add_argument("--output", required=True)
    parser.add_argument("--direction", default="ue_to_remote")
    parser.add_argument("--port-base", type=int, default=5000)
    parser.add_argument("--bind-ip", default=None)
    parser.add_argument("--server", help="Server IP address; required in client mode")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--qos", action="store_true")
    parser.add_argument("--audio-interval-ms", type=float, default=20.0)
    parser.add_argument("--control-rate", type=float, default=100.0)
    parser.add_argument("--video-fps", type=float, default=30.0)
    parser.add_argument("--record-one-way-delay", action="store_true")
    parser.add_argument("--audio-deadline-ms", type=float, default=None)
    parser.add_argument("--video-deadline-ms", type=float, default=None)
    parser.add_argument("--control-deadline-ms", type=float, default=None)
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.duration <= 0:
        parser.error("--duration must be > 0")
    if args.mode == "client" and not args.server:
        parser.error("--server is required in client mode")
    if args.mode == "server" and args.bind_ip is None:
        args.bind_ip = "0.0.0.0"
    if args.control_rate <= 0 or args.video_fps <= 0 or args.audio_interval_ms <= 0:
        parser.error("traffic rates/intervals must be > 0")
    if args.mode == "server":
        run_server(args)
    else:
        run_client(args)


if __name__ == "__main__":
    main()
