"""Tests for optional import/export operation metrics."""

import contextlib
import io
import json
import os
import time
import unittest
from unittest.mock import patch

from adm_blender.core.qa_metrics import record_success


class QaMetricsTests(unittest.TestCase):
    def test_metrics_are_silent_without_the_qa_flag(self):
        output = io.StringIO()
        with patch.dict(os.environ, {}, clear=False), contextlib.redirect_stdout(output):
            os.environ.pop("ADM_QA_METRICS", None)
            record_success("model_import", time.perf_counter())
        self.assertEqual(output.getvalue(), "")

    def test_qa_flag_emits_machine_readable_success_metric(self):
        output = io.StringIO()
        with patch.dict(os.environ, {"ADM_QA_METRICS": "1"}), contextlib.redirect_stdout(output):
            record_success("model_export", time.perf_counter())
        prefix, payload = output.getvalue().strip().split(":", 1)
        metric = json.loads(payload)
        self.assertEqual(prefix, "ADM_QA_METRIC")
        self.assertEqual(metric["operation"], "model_export")
        self.assertEqual(metric["status"], "PASS")
        self.assertGreaterEqual(metric["duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
