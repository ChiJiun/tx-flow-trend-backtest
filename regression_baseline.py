"""Versioned reference for the fixed-data backtest; accounting assertions remain in backtest.py."""
from pathlib import Path
import json
import math

BASELINE_PATH = Path(__file__).resolve().with_name("regression_baseline.json")


def verify_regression_baseline(actual, path=BASELINE_PATH):
    expected = json.loads(Path(path).read_text(encoding="utf-8"))
    if expected.get("schema_version") != 1:
        raise ValueError(f"Unsupported regression baseline schema version: {expected.get('schema_version')!r}")
    differences = []
    for key in ("period", "parameters", "input_sha256"):
        if actual[key] != expected[key]:
            differences.append(f"{key}: expected {expected[key]!r}; actual {actual[key]!r}")
    for key, reference in expected["metrics"].items():
        value = actual["metrics"].get(key)
        tolerance = expected.get("absolute_tolerance", {}).get(key, 0)
        if value is None or not math.isclose(value, reference, rel_tol=0, abs_tol=tolerance):
            differences.append(f"metrics.{key}: expected {reference!r} (±{tolerance}); actual {value!r}")
    if differences:
        raise AssertionError(
            "Regression baseline mismatch:" + chr(10) + chr(10).join(differences)
            + chr(10) + "For an intentional input/period/parameter change, review the accounting results "
            "and update regression_baseline.json with an incremented baseline_revision and the source hashes."
        )
