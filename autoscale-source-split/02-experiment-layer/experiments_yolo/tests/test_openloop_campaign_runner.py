#!/usr/bin/env python3
import importlib.util
import argparse
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
RUNNER = ROOT / "autoscale-source-split/02-experiment-layer/experiments_yolo/openloop_load_thermal_campaign/openloop_campaign_runner.py"
DATASET_BUILDER = ROOT / "autoscale-source-split/02-experiment-layer/experiments_yolo/common/build_openloop_load_conditioned_dataset.py"


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


runner = load_module(RUNNER)
dataset_builder = load_module(DATASET_BUILDER)


def v2_config_fields():
    return {
        "normal_baseline_v2": {
            "campaign_id": "c1",
            "replicate_id": "r1",
            "run_order": 1,
            "warmup_duration_s": 1,
            "measurement_duration_s": 3,
            "post_observation_duration_s": 1,
        },
        "latency_target_policy": {
            "primary_latency_target": "rolling_median",
            "default_window_s": 3,
            "default_min_samples": 1,
            "default_min_tail_samples": 3,
        },
    }


class CampaignRunnerValidationTest(unittest.TestCase):
    def test_config_requires_normal_cooling(self):
        cfg = {
            "campaign_name": "x",
            "endpoint": {"url": "http://example.invalid"},
            "workload_profiles": {"low": {"target_rps": 1, "duration_s": 10, "max_inflight": 1}},
            "cooling_conditions": {"cooling_constrained": {}},
            "replicates": 1,
            "safety": {"operator_max_gpu_temp_c": None},
        }
        errors, warnings = runner.validate_config(cfg, strict=False)
        self.assertTrue(any("normal_cooling" in e for e in errors))
        self.assertTrue(any("operator_max_gpu_temp_c" in w for w in warnings))

    def test_normal_only_matrix_excludes_cooling_constrained(self):
        cfg = {
            "workload_profiles": {"low": {"target_rps": 1, "duration_s": 10, "max_inflight": 1}},
            "cooling_conditions": {"normal_cooling": {}, "cooling_constrained": {}, "recovery_observation": {}},
            "replicates": 2,
        }
        matrix = runner.expand_matrix(cfg, normal_only=True)
        self.assertEqual(len(matrix), 2)
        self.assertEqual({m["cooling_condition"] for m in matrix}, {"normal_cooling"})

    def test_raw_fingerprint_excludes_new_output_but_detects_existing_raw_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw = root / "singlepod_bgcycle_test_run"
            raw.mkdir()
            raw_file = raw / "measurement_raw.csv"
            raw_file.write_text("a\n", encoding="utf-8")
            raw_dirs = runner.discover_raw_run_dirs(root)
            before = runner.collect_tree_fingerprint(root, raw_dirs)
            out_dir = root / "openloop_load_thermal_campaign" / "dryrun_x"
            out_dir.mkdir(parents=True)
            (out_dir / "run_manifest.json").write_text("{}", encoding="utf-8")
            after_output = runner.collect_tree_fingerprint(root, raw_dirs)
            self.assertEqual(before, after_output)
            time.sleep(0.001)
            raw_file.write_text("b\n", encoding="utf-8")
            after_raw = runner.collect_tree_fingerprint(root, raw_dirs)
            self.assertNotEqual(before, after_raw)

    def test_run_campaign_fails_closed_even_when_confirmed(self):
        cfg = {
            "campaign_name": "x",
            "endpoint": {"url": "http://example.invalid"},
            "workload_profiles": {"low": {"target_rps": 1, "duration_s": 10, "max_inflight": 1}},
            "cooling_conditions": {"normal_cooling": {}},
            "replicates": 1,
            "safety": {"operator_max_gpu_temp_c": 80},
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "cfg.json"
            config_path.write_text(__import__("json").dumps(cfg), encoding="utf-8")
            old = os.environ.get("CONFIRM_EXPERIMENT")
            os.environ["CONFIRM_EXPERIMENT"] = "YES"
            try:
                code = runner.run(
                    argparse.Namespace(
                        config=str(config_path),
                        out_root=str(Path(tmp) / "out"),
                        dry_run=False,
                        preflight_only=False,
                        run_campaign=True,
                        run_normal_smoke=False,
                        calibrate_normal=False,
                        normal_only=False,
                    )
                )
            finally:
                if old is None:
                    os.environ.pop("CONFIRM_EXPERIMENT", None)
                else:
                    os.environ["CONFIRM_EXPERIMENT"] = old
            self.assertNotEqual(code, 0)

    def test_normal_smoke_requires_normal_only_and_confirm(self):
        cfg = {
            "campaign_name": "x",
            "endpoint": {"url": "http://example.invalid"},
            "workload_profiles": {"low": {"target_rps": 1, "duration_s": 10, "max_inflight": 1}},
            "cooling_conditions": {"normal_cooling": {}},
            "replicates": 1,
            "safety": {"operator_max_gpu_temp_c": 80},
            "normal_live_smoke": {
                "target_rps": 1,
                "duration_s": 1,
                "max_inflight": 1,
                "payload_mix": ["missing.jpg"],
            },
            **v2_config_fields(),
        }
        with tempfile.TemporaryDirectory() as tmp:
            config_path = Path(tmp) / "cfg.json"
            config_path.write_text(__import__("json").dumps(cfg), encoding="utf-8")
            code = runner.run(
                argparse.Namespace(
                    config=str(config_path),
                    out_root=str(Path(tmp) / "out"),
                    dry_run=False,
                    preflight_only=False,
                    run_campaign=False,
                    run_normal_smoke=True,
                    calibrate_normal=False,
                    normal_only=False,
                )
            )
            self.assertNotEqual(code, 0)

    def test_calibration_profiles_from_config(self):
        cfg = {
            "normal_live_smoke": {"duration_s": 3, "max_inflight": 2, "payload_mix": ["a.jpg"]},
            "calibration": {"candidate_offered_rps": [0.5, 1.0], "duration_s": 2, "max_inflight": 4},
        }
        profiles = runner.calibration_profiles(cfg)
        self.assertEqual([p["target_rps"] for p in profiles], [0.5, 1.0])
        self.assertEqual(profiles[0]["duration_s"], 2)
        self.assertEqual(profiles[0]["max_inflight"], 4)

    def test_live_normal_rejects_fan_control_metadata(self):
        cfg = {
            "campaign_name": "x",
            "endpoint": {"url": "http://example.invalid"},
            "workload_profiles": {"low": {"target_rps": 1, "duration_s": 10, "max_inflight": 1}},
            "cooling_conditions": {
                "normal_cooling": {"fan_control_allowed": False, "primary_control": "none"},
                "cooling_constrained": {"fan_control_allowed": True, "primary_control": "operator-approved-cooling-profile"},
            },
            "replicates": 1,
            "safety": {"operator_max_gpu_temp_c": 80},
            "normal_live_smoke": {
                "target_rps": 1,
                "duration_s": 1,
                "max_inflight": 1,
                "payload_mix": ["missing.jpg"],
            },
            **v2_config_fields(),
        }
        errors, _ = runner.validate_config(cfg, strict=True, live_normal=True)
        self.assertTrue(any("fan-control cooling condition" in e for e in errors))

    def test_live_normal_rejects_operator_placeholders(self):
        cfg = {
            "campaign_name": "x",
            "endpoint": {"url": "operator-confirm-current-yolo-endpoint"},
            "node_gpu_identity": {"node_name": "operator-confirm-current-node"},
            "workload_profiles": {"low": {"target_rps": 1, "duration_s": 10, "max_inflight": 1}},
            "cooling_conditions": {"normal_cooling": {"fan_control_allowed": False, "primary_control": "none"}},
            "replicates": 1,
            "safety": {"operator_max_gpu_temp_c": 80},
            "normal_live_smoke": {
                "target_rps": 1,
                "duration_s": 1,
                "max_inflight": 1,
                "payload_mix": ["missing.jpg"],
            },
            **v2_config_fields(),
        }
        errors, _ = runner.validate_config(cfg, strict=True, live_normal=True)
        self.assertTrue(any("endpoint.url" in e for e in errors))
        self.assertTrue(any("node_gpu_identity.node_name" in e for e in errors))

    def test_normal_v2_requires_manifest_collection_fields_for_live(self):
        cfg = {
            "campaign_name": "x",
            "endpoint": {"url": "http://example.invalid"},
            "node_gpu_identity": {"node_name": "node", "gpu_uuid": "uuid"},
            "workload_profiles": {"low": {"target_rps": 1, "duration_s": 10, "max_inflight": 1}},
            "cooling_conditions": {"normal_cooling": {"fan_control_allowed": False, "primary_control": "none"}},
            "replicates": 1,
            "safety": {"operator_max_gpu_temp_c": 80},
            "normal_live_smoke": {
                "target_rps": 1,
                "duration_s": 1,
                "max_inflight": 1,
                "payload_mix": ["missing.jpg"],
            },
        }
        errors, _ = runner.validate_config(cfg, strict=True, live_normal=True)
        self.assertTrue(any("normal_baseline_v2.campaign_id" in e for e in errors))
        self.assertTrue(any("latency_target_policy" in e for e in errors))

    def test_synthetic_run_window_extraction_marks_only_measurement_rows_eligible(self):
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "run1"
            run_dir.mkdir()
            (run_dir / "open_loop_arrival_1s_summary.csv").write_text(
                "elapsed_s,scheduled_request_count,launched_request_count,dropped_max_inflight_count,inflight_count_max,client_backlog_or_schedule_miss,timeout_rate,fail_rate\n"
                + "\n".join(f"{i},1,1,0,1,0,0,0" for i in range(6))
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "open_loop_completion_1s_summary.csv").write_text(
                "elapsed_s,realized_completed_rps,completed_request_count,successful_completion_count,latency_p50,latency_p95,latency_p99\n"
                + "\n".join(f"{i},1,1,1,10,10,10" for i in range(6))
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "open_loop_client_raw.csv").write_text(
                "complete_elapsed_s,e2e_latency_ms,success\n"
                + "\n".join(f"{i}.1,10,True" for i in range(6))
                + "\n",
                encoding="utf-8",
            )
            manifest = {
                "campaign_id": "c1",
                "replicate_id": "r1",
                "target_offered_rps": 1.0,
                "run_order": 1,
                "warmup_start_ts": "2026-07-03T00:00:00+00:00",
                "warmup_end_ts": "2026-07-03T00:00:02+00:00",
                "measurement_start_ts": "2026-07-03T00:00:02+00:00",
                "measurement_end_ts": "2026-07-03T00:00:05+00:00",
                "client_start_ts": "2026-07-03T00:00:00+00:00",
                "client_stop_ts": "2026-07-03T00:00:06+00:00",
                "endpoint_identity": {"url": "http://example.invalid"},
                "model": "m",
                "image_set_hash": "hash",
                "node_gpu_identity": {"gpu_uuid": "uuid"},
                "background_workload_state": {"enabled": False},
                "telemetry_source_availability": {"nvidia_smi_gpu_1s": True},
                "telemetry_sample_age_summary": {"nvidia_smi_rows": 6},
                "offered_load_profile": {"target_rps": 1.0},
            }
            (run_dir / "run_manifest.json").write_text(__import__("json").dumps(manifest), encoding="utf-8")
            df = dataset_builder.run_rows(run_dir, latency_window_s=2, latency_min_samples=1)
            eligible_elapsed = df[df["eligible_for_formal_validation"]]["elapsed_s"].tolist()
            self.assertEqual(eligible_elapsed, [2, 3, 4])
            self.assertFalse(df["analysis_ineligible"].any())


if __name__ == "__main__":
    unittest.main()
