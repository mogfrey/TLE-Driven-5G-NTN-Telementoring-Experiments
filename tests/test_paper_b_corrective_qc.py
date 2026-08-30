import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from paper_b_corrective_qc import evaluate


def write_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n")


def write_windows(path: Path, n=5, alive=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for _ in range(n):
            v = 1.0 if alive else 0.0
            f.write(json.dumps({
                "data_plane_alive": alive,
                "metrics": {
                    "video_frame_delivery_ratio": v,
                    "audio_uplink_packet_delivery_ratio": v,
                    "audio_downlink_packet_delivery_ratio": v,
                    "telestration_ack_delivery_ratio": v,
                },
            }) + "\n")


def base_run(tmp_path: Path):
    app = tmp_path / "application"
    write_json(app / "run_status.json", {"status": "pass"})
    write_json(app / "receiver_lifecycle.json", {
        "audio_uplink": {"wall_runtime_s": 181.0, "premature_timeout": False, "exit_reason": "normal_or_post_measurement_cleanup"},
        "audio_downlink": {"wall_runtime_s": 181.0, "premature_timeout": False, "exit_reason": "normal_or_post_measurement_cleanup"},
    })
    write_windows(tmp_path / "analysis/usability_windows.jsonl")
    return tmp_path


def test_valid_corrective_run(tmp_path):
    report = evaluate(base_run(tmp_path), 180.0, 5, 1.0)
    assert report["instrumentation_valid"] is True
    assert report["required_receiver_observation_lifetime_s"] == 180.0
    assert report["scientific_outcome_used_for_qc"] is False


def test_premature_timeout_fails(tmp_path):
    run = base_run(tmp_path)
    (run / "application/bundled_workload_console.log").write_text(
        "line 56: Killed timeout --kill-after=5s --signal=INT 185 ffmpeg ...\n"
    )
    report = evaluate(run, 180.0, 5, 1.0)
    assert report["instrumentation_valid"] is False
    assert "legacy_or_premature_receiver_timeout_detected" in report["reasons"]


def test_zero_startup_data_fails(tmp_path):
    run = base_run(tmp_path)
    write_windows(run / "analysis/usability_windows.jsonl", alive=False)
    report = evaluate(run, 180.0, 5, 1.0)
    assert report["instrumentation_valid"] is False
    assert "multimodal_path_not_alive_at_startup" in report["reasons"]
    assert "no_application_data_observed" in report["reasons"]


def test_short_receiver_lifetime_fails_full_duration_conditions(tmp_path):
    run = base_run(tmp_path)
    write_json(run / "application/receiver_lifecycle.json", {
        "audio_uplink": {"wall_runtime_s": 164.5, "premature_timeout": False},
        "audio_downlink": {"wall_runtime_s": 165.0, "premature_timeout": False},
    })
    report = evaluate(run, 180.0, 5, 1.0)
    assert report["instrumentation_valid"] is False
    assert "receiver_lifetime_short:audio_uplink" in report["reasons"]
    assert "receiver_lifetime_short:audio_downlink" in report["reasons"]


def test_near_failure_can_use_radio_boundary_observation_interval(tmp_path):
    run = base_run(tmp_path)
    write_json(run / "application/receiver_lifecycle.json", {
        "audio_uplink": {"wall_runtime_s": 150.2, "premature_timeout": False, "exit_reason": "condition_induced_service_loss"},
        "audio_downlink": {"wall_runtime_s": 150.0, "premature_timeout": False, "exit_reason": "condition_induced_service_loss"},
    })
    report = evaluate(run, 180.0, 5, 1.0, required_lifetime_s=149.7)
    assert report["instrumentation_valid"] is True
    assert report["required_receiver_observation_lifetime_s"] == 149.7


def test_premature_timeout_still_fails_with_shorter_required_interval(tmp_path):
    run = base_run(tmp_path)
    write_json(run / "application/receiver_lifecycle.json", {
        "audio_uplink": {"wall_runtime_s": 150.2, "premature_timeout": True},
        "audio_downlink": {"wall_runtime_s": 150.0, "premature_timeout": False},
    })
    report = evaluate(run, 180.0, 5, 1.0, required_lifetime_s=149.7)
    assert report["instrumentation_valid"] is False
    assert "premature_receiver_timeout:audio_uplink" in report["reasons"]
