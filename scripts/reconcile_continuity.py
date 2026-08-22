#!/usr/bin/env python3
"""Reconcile sender/receiver JSON into continuity-aware run metrics.

Supports both:
1. the portable ``scripts/continuity_benchmark.py`` schema; and
2. archived Málaga benchmark JSONs with ``packets_sent`` / ``frames_sent``.

The key distinction is between receiver-visible prefix loss and whole-session
completion. A receiver can only infer loss inside the sequence prefix it has
observed; sender reconciliation is required to quantify an unobserved terminal
suffix.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def sender_units(flow: dict[str, Any]) -> int | None:
    for key in ("units_generated", "packets_sent"):
        value = flow.get(key)
        if value is not None:
            return int(value)
    return None


def sender_socket_successes(flow: dict[str, Any]) -> int | None:
    value = flow.get("socket_send_successes")
    return int(value) if value is not None else None


def receiver_unique(flow: dict[str, Any]) -> int | None:
    for key in ("unique_sequences_received", "packets_received"):
        value = flow.get(key)
        if value is not None:
            return int(value)
    return None


def receiver_highest_seq(flow: dict[str, Any]) -> int | None:
    value = flow.get("highest_sequence_received")
    if value is not None:
        return int(value)
    expected = flow.get("prefix_expected_packets", flow.get("expected_packets"))
    if expected is not None and int(expected) > 0:
        return int(expected) - 1
    return None


def receiver_prefix_expected(flow: dict[str, Any]) -> int | None:
    for key in ("prefix_expected_packets", "expected_packets"):
        value = flow.get(key)
        if value is not None:
            return int(value)
    highest = receiver_highest_seq(flow)
    return highest + 1 if highest is not None else None


def ratio(num: float | int | None, den: float | int | None) -> float | None:
    if num is None or den in (None, 0):
        return None
    return float(num) / float(den)


def flow_metrics(name: str, tx: dict[str, Any], rx: dict[str, Any], duration_s: float | None) -> dict[str, Any]:
    generated = sender_units(tx)
    socket_ok = sender_socket_successes(tx)
    received = receiver_unique(rx)
    prefix_expected = receiver_prefix_expected(rx)
    highest = receiver_highest_seq(rx)

    prefix_missing = None
    if prefix_expected is not None and received is not None:
        prefix_missing = max(prefix_expected - received, 0)

    terminal_suffix = None
    if generated is not None:
        terminal_suffix = generated if highest is None else max(generated - (highest + 1), 0)

    session_completion = ratio(received, generated)
    socket_delivery = ratio(received, socket_ok)
    prefix_loss = ratio(prefix_missing, prefix_expected)
    terminal_fraction = ratio(terminal_suffix, generated)

    continuity_deficit_s = None
    if terminal_suffix is not None and generated and duration_s and duration_s > 0:
        achieved_generation_rate = generated / duration_s
        continuity_deficit_s = terminal_suffix / achieved_generation_rate

    result: dict[str, Any] = {
        "generated_units": generated,
        "socket_send_successes": socket_ok,
        "socket_send_errors": tx.get("socket_send_errors"),
        "received_unique_units": received,
        "receiver_highest_sequence": highest,
        "receiver_prefix_expected_units": prefix_expected,
        "receiver_prefix_missing_units": prefix_missing,
        "receiver_prefix_loss_fraction": prefix_loss,
        "session_completion_ratio": session_completion,
        "whole_session_missing_fraction": None if session_completion is None else 1.0 - session_completion,
        "socket_input_delivery_ratio": socket_delivery,
        "terminal_suffix_units": terminal_suffix,
        "terminal_censoring_fraction": terminal_fraction,
        "continuity_deficit_duration_s": continuity_deficit_s,
        "first_receive_time_ns": rx.get("first_receive_time_ns"),
        "last_receive_time_ns": rx.get("last_receive_time_ns"),
        "receiver_reported_loss_percent": rx.get("prefix_loss_percent", rx.get("estimated_loss_percent")),
    }

    if name == "video":
        generated_frames = tx.get("frames_generated", tx.get("frames_sent"))
        complete_frames = rx.get("video_complete_frames")
        if generated_frames is not None:
            generated_frames = int(generated_frames)
        if complete_frames is not None:
            complete_frames = int(complete_frames)
        result.update(
            {
                "generated_frames": generated_frames,
                "complete_received_frames": complete_frames,
                "frame_session_completion_ratio": ratio(complete_frames, generated_frames),
            }
        )

    return result


def finite(values: list[float | None]) -> list[float]:
    return [float(v) for v in values if v is not None and math.isfinite(float(v))]


def reconcile(sender: dict[str, Any], receiver: dict[str, Any]) -> dict[str, Any]:
    sender_flows = sender.get("flows", {})
    receiver_flows = receiver.get("flows", {})
    common_flows = sorted(set(sender_flows) & set(receiver_flows))
    if not common_flows:
        raise ValueError("No common flow names found in sender/receiver JSON")

    duration = sender.get("duration_s")
    duration_s = float(duration) if duration is not None else None
    flows = {
        name: flow_metrics(name, sender_flows[name], receiver_flows[name], duration_s)
        for name in common_flows
    }

    completion_values = finite([m["session_completion_ratio"] for m in flows.values()])
    deficit_values = finite([m["continuity_deficit_duration_s"] for m in flows.values()])
    last_rx_ns = [
        int(m["last_receive_time_ns"])
        for m in flows.values()
        if m.get("last_receive_time_ns") is not None
    ]

    aggregate: dict[str, Any] = {
        "flow_count": len(flows),
        "mean_session_completion_ratio": (
            sum(completion_values) / len(completion_values) if completion_values else None
        ),
        "cross_stream_completion_spread": (
            max(completion_values) - min(completion_values) if len(completion_values) >= 2 else None
        ),
        "mean_continuity_deficit_duration_s": (
            sum(deficit_values) / len(deficit_values) if deficit_values else None
        ),
        "cross_stream_deficit_spread_s": (
            max(deficit_values) - min(deficit_values) if len(deficit_values) >= 2 else None
        ),
        "cross_stream_last_receive_skew_ms": (
            (max(last_rx_ns) - min(last_rx_ns)) / 1_000_000.0 if len(last_rx_ns) >= 2 else None
        ),
    }

    return {
        "schema_version": 1,
        "analysis": "continuity_sender_receiver_reconciliation",
        "run_id": sender.get("run_id") or receiver.get("run_id"),
        "workload": sender.get("workload") or receiver.get("workload"),
        "duration_s": duration_s,
        "sender_schema_version": sender.get("schema_version"),
        "receiver_schema_version": receiver.get("schema_version"),
        "flows": flows,
        "aggregate": aggregate,
        "definitions": {
            "receiver_prefix_loss_fraction": (
                "Missing sequence numbers within 0..highest_sequence_received divided by the "
                "receiver-visible prefix length. This cannot represent an unseen terminal suffix."
            ),
            "session_completion_ratio": "received unique units divided by application-generated units",
            "terminal_censoring_fraction": (
                "application-generated sequence units above the receiver's highest observed sequence "
                "divided by total generated units"
            ),
            "continuity_deficit_duration_s": (
                "terminal suffix units divided by the sender's run-level achieved generation rate"
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Reconcile continuity benchmark sender/receiver results")
    parser.add_argument("--sender", required=True, help="Sender/client JSON")
    parser.add_argument("--receiver", required=True, help="Receiver/server JSON")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    result = reconcile(load_json(args.sender), load_json(args.receiver))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    aggregate = result["aggregate"]
    completion = aggregate["mean_session_completion_ratio"]
    deficit = aggregate["mean_continuity_deficit_duration_s"]
    print(f"wrote continuity reconciliation: {output}")
    if completion is not None:
        print(f"mean session completion: {100.0 * completion:.3f}%")
    if deficit is not None:
        print(f"mean continuity deficit: {deficit:.3f} s")


if __name__ == "__main__":
    main()
