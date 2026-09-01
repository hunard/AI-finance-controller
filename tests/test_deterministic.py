"""
Basic regression tests for the functions that broke at least once during
development - these exist specifically so those bugs can't silently
come back if the code gets edited later.

Run with: python tests/test_deterministic.py
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from engine.deterministic import parse_amount, parse_date, diagnose_settlement_gap, expected_settlement


def test_parse_amount_strips_commas():
    assert parse_amount("1,999.00") == 1999.0

def test_parse_amount_no_commas():
    assert parse_amount("1999") == 1999.0

def test_parse_amount_decimals():
    assert parse_amount("299.00") == 299.0


def test_parse_date_gateway_format():
    d = parse_date("2026-08-14 00:00:00", "gateway")
    assert d.year == 2026 and d.month == 8 and d.day == 14

def test_parse_date_bank_format():
    d = parse_date("14-08-2026", "bank")
    assert d.year == 2026 and d.month == 8 and d.day == 14

def test_parse_date_ledger_format():
    d = parse_date("14/08/2026", "ledger")
    assert d.year == 2026 and d.month == 8 and d.day == 14

def test_all_three_date_formats_agree():
    g = parse_date("2026-08-14 00:00:00", "gateway")
    b = parse_date("14-08-2026", "bank")
    l = parse_date("14/08/2026", "ledger")
    assert g == b == l


def test_diagnose_correct_settlement():
    breakdown = expected_settlement(1999.0, "UPI")
    result = diagnose_settlement_gap(1999.0, "UPI", breakdown["expected_net"])
    assert result["status"] == "correct"

def test_diagnose_tds_double_deducted():
    breakdown = expected_settlement(1999.0, "UPI")
    actual = breakdown["expected_net"] - breakdown["tds"]
    result = diagnose_settlement_gap(1999.0, "UPI", actual)
    assert result["status"] == "mismatch"
    assert "twice" in result["reason"]

def test_diagnose_commission_missing():
    breakdown = expected_settlement(1999.0, "UPI")
    actual = breakdown["expected_net"] + breakdown["commission"]
    result = diagnose_settlement_gap(1999.0, "UPI", actual)
    assert result["status"] == "mismatch"
    assert "commission" in result["reason"]


if __name__ == "__main__":
    tests = [obj for name, obj in list(globals().items()) if name.startswith("test_") and callable(obj)]
    passed, failed = 0, 0
    for t in tests:
        try:
            t()
            print(f"PASS: {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL: {t.__name__} - {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed")