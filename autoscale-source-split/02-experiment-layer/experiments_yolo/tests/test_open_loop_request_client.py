#!/usr/bin/env python3
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
CLIENT = ROOT / "autoscale-source-split/02-experiment-layer/experiments_yolo/common/open_loop_request_client.py"


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


client = load_module(CLIENT)


class OpenLoopScheduleTest(unittest.TestCase):
    def test_constant_schedule_uses_offered_arrivals(self):
        segments = [client.RateSegment(name="constant", start_s=0.0, end_s=2.0, target_rps=2.0)]
        schedule = client.build_schedule(2.0, segments)
        self.assertEqual(len(schedule), 4)
        self.assertEqual([r["scheduled_elapsed_s"] for r in schedule], [0.0, 0.5, 1.0, 1.5])

    def test_piecewise_schedule_keeps_profile_names(self):
        segments = [
            client.RateSegment(name="low", start_s=0.0, end_s=1.0, target_rps=1.0),
            client.RateSegment(name="high", start_s=1.0, end_s=2.0, target_rps=2.0),
        ]
        schedule = client.build_schedule(2.0, segments)
        self.assertEqual([r["profile_name"] for r in schedule], ["low", "high", "high"])

    def test_aggregation_separates_scheduled_from_completed(self):
        rows = [
            {
                "scheduled_elapsed_s": 0.0,
                "complete_elapsed_s": 2.1,
                "launch_status": "launched",
                "complete_time_iso": "x",
                "success": True,
                "e2e_latency_ms": 10,
                "inflight_at_schedule": 0,
            },
            {
                "scheduled_elapsed_s": 0.5,
                "launch_status": "dropped_max_inflight",
                "success": False,
                "error_type": "max_inflight",
                "inflight_at_schedule": 8,
            },
        ]
        summary = client.aggregate_rows(rows)
        self.assertEqual(summary[0]["scheduled_request_count"], 2)
        self.assertEqual(summary[0]["launched_request_count"], 1)
        self.assertEqual(summary[0]["dropped_max_inflight_count"], 1)
        self.assertEqual(summary[0]["arrival_bin_completed_count"], 1)
        self.assertEqual(summary[0]["client_backlog_or_schedule_miss"], 1)

    def test_completion_binned_summary_uses_completion_time(self):
        rows = [
            {
                "scheduled_elapsed_s": 0.0,
                "complete_elapsed_s": 2.1,
                "launch_status": "launched",
                "complete_time_iso": "x",
                "success": True,
                "e2e_latency_ms": 10,
                "inflight_at_schedule": 0,
            },
            {
                "scheduled_elapsed_s": 0.5,
                "complete_elapsed_s": 2.8,
                "launch_status": "launched",
                "complete_time_iso": "x",
                "success": False,
                "error_type": "timeout",
                "e2e_latency_ms": 1000,
                "inflight_at_schedule": 1,
            },
        ]
        arrival = client.aggregate_arrival_binned_rows(rows)
        completion = client.aggregate_completion_binned_rows(rows)
        self.assertEqual(arrival[0]["scheduled_request_count"], 2)
        self.assertEqual(completion[0]["elapsed_s"], 2)
        self.assertEqual(completion[0]["completed_request_count"], 2)
        self.assertEqual(completion[0]["successful_completion_count"], 1)
        self.assertEqual(completion[0]["timeout_completion_count"], 1)

    def test_urllib_wrapped_timeout_classifies_timeout(self):
        import socket
        import urllib.error

        err = urllib.error.URLError(socket.timeout("timed out"))
        self.assertEqual(client.classify_url_error(err), "timeout")


if __name__ == "__main__":
    unittest.main()
