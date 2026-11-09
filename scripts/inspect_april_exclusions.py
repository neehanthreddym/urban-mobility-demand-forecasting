#!/usr/bin/env python3
"""Inspect April exclusions using the original screening report and output format."""

from pathlib import Path

from inspect_month_exclusions import inspect as inspect_month
from inspect_month_exclusions import main as monthly_main
from inspect_month_exclusions import write_outputs


def inspect(baseline_path: Path) -> tuple[dict, list[dict], list[dict]]:
    """Reconcile April records using the historical report fields.

    Args:
        baseline_path: Legacy April quality report JSON.

    Output:
        Aggregate report, local date excerpts, and geographic group counts.
    """
    return inspect_month(baseline_path, "2025-04", legacy=True)


def main() -> int:
    """Run the original April CLI and return its reconciliation exit code."""
    return monthly_main(legacy=True)


if __name__ == "__main__":
    raise SystemExit(main())
