"""Optional operation metrics for the repository QA runner."""

import json
import os
import time


def record_success(operation, started_at):
    if os.environ.get("ADM_QA_METRICS") != "1":
        return
    metric = {
        "operation": operation,
        "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
        "status": "PASS",
    }
    print("ADM_QA_METRIC:" + json.dumps(metric, separators=(",", ":")), flush=True)
