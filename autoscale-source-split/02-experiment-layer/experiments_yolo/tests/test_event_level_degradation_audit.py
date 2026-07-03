#!/usr/bin/env python3
import importlib.util
import sys
import unittest
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[4]
AUDIT = ROOT / "autoscale-source-split/02-experiment-layer/experiments_yolo/common/offline_event_level_degradation_audit.py"


def load_module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[path.stem] = module
    spec.loader.exec_module(module)
    return module


audit = load_module(AUDIT)


class EventLevelAuditTest(unittest.TestCase):
    def test_string_boolean_parsing(self):
        s = pd.Series(["False", "true", "0", "1", "healthy", "degraded"])
        parsed = audit.parse_boolean_series(s, "x").tolist()
        self.assertEqual(parsed, [False, True, False, True, False, True])

    def test_onset_at_first_sample_excluded(self):
        df = pd.DataFrame({"run_id": ["r1", "r1", "r1"], "time_s": [0, 10, 20], "degraded": [True, True, False]})
        onsets = audit.identify_onsets(df, "run_id", "time_s", "degraded", min_healthy_runin_s=1)
        self.assertTrue(onsets.empty)

    def test_min_max_lead_time_window(self):
        df = pd.DataFrame(
            {
                "run_id": ["r1"] * 6,
                "time_s": [0, 10, 20, 30, 40, 50],
                "degraded": [False, False, False, False, False, True],
                "warning": [False, True, False, True, False, False],
            }
        )
        df["degraded"] = audit.parse_boolean_series(df["degraded"], "degraded")
        df["warning"] = audit.parse_boolean_series(df["warning"], "warning")
        onsets = audit.identify_onsets(df, "run_id", "time_s", "degraded", min_healthy_runin_s=1)
        alerts = audit.debounce_alerts(df, "run_id", "time_s", "warning", refractory_s=1)
        event_df, metrics = audit.event_metrics(
            df,
            onsets,
            alerts,
            "run_id",
            "time_s",
            min_lead_s=15,
            max_lead_s=25,
            healthy_mask=~df["degraded"],
        )
        self.assertTrue(bool(event_df.iloc[0]["detected"]))
        self.assertEqual(event_df.iloc[0]["lead_time_s"], 20)
        self.assertEqual(metrics["event_recall"], 1.0)

    def test_alert_debounce(self):
        df = pd.DataFrame({"run_id": ["r1"] * 4, "time_s": [0, 5, 20, 21], "warning": [True, True, True, True]})
        alerts = audit.debounce_alerts(df, "run_id", "time_s", "warning", refractory_s=10)
        self.assertEqual(alerts["alert_time_s"].tolist(), [0.0, 20.0])


if __name__ == "__main__":
    unittest.main()
