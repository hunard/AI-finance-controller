"""
run_daily.py

Demonstrates how this reconciliation engine would run in production:
as a scheduled job right after each settlement cycle completes, not
triggered by hand.

This is NOT deployed anywhere - there's no live server or cron job
actually running this. It's a stub showing the intended production
pattern: pull fresh data, run the full pipeline, write the exception
report somewhere a finance team would actually see it.

In a real deployment, fetch_latest_sources() below would call
Razorpay's Settlement API, a bank API/account aggregator, and the
merchant's accounting software API - instead of reading local CSVs.
"""

import json
from datetime import datetime
from pathlib import Path

from engine.deterministic import (
    load_csv, normalise, match_pair_with_date_tolerance,
    match_gateway_to_bank,find_splits_first,GATEWAY_FILE, BANK_FILE, LEDGER_FILE,
)
from engine.report import build_final_report
from engine.LLM_resolver import resolve_unmatched, apply_llm_layer


def fetch_latest_sources():
    gateway = normalise(load_csv(GATEWAY_FILE), "gateway", "amount", "created_at")
    bank = normalise(load_csv(BANK_FILE), "bank", "credit", "value_date")
    ledger = normalise(load_csv(LEDGER_FILE), "ledger", "credit", "entry_date")
    return gateway, bank, ledger


def run_reconciliation_job():
    print(f"[{datetime.now().isoformat()}] Starting scheduled reconciliation run...")

    gateway, bank, ledger = fetch_latest_sources()

    ledger_matched, ledger_leftover_gw, _ = match_pair_with_date_tolerance(gateway, ledger)

    split_matched, gateway_after_splits, bank_after_splits = find_splits_first(gateway, bank)
    bank_matched_11, bank_leftover_gw, bank_leftover_bank = match_gateway_to_bank(gateway_after_splits, bank_after_splits)
    bank_matched = split_matched + bank_matched_11

    report = build_final_report(gateway, ledger_matched, ledger_leftover_gw, bank_matched, bank_leftover_gw)
    report = apply_llm_layer(report, bank_leftover_gw, bank_leftover_bank)

    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    output_path = output_dir / f"reconciliation_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

    with open(output_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    counts = {}
    for entry in report:
        counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1

    print(f"Run complete. {len(report)} transactions processed.")
    print(f"Breakdown: {counts}")
    print(f"Full report written to: {output_path}")

    exceptions = [e for e in report if e["verdict"] not in ("fully_reconciled",)]
    print(f"{len(exceptions)} transactions need finance-team attention.")

    return report


if __name__ == "__main__":
    # In production: invoked by a scheduler (cron, Airflow, a cloud
    # scheduler trigger) once per settlement cycle - e.g. "0 6 * * *"
    # for daily at 6am, right after Razorpay's T+2 settlement clears.
    run_reconciliation_job()