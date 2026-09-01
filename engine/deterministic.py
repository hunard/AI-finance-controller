import csv
from pathlib import Path
from datetime import datetime
from collections import defaultdict
GATEWAY_FILE=Path("payment_gateway.csv")
BANK_FILE=Path("bank_statement.csv")
LEDGER_FILE=Path("merchant_ledger.csv")
def load_csv(path):
        with open(path,newline="",encoding="utf-8") as f:
            return list(csv.DictReader(f))


def parse_amount(raw):
    return float(raw.replace(",", ""))


def parse_date(raw, source):
    formats = {
        "gateway": "%Y-%m-%d %H:%M:%S",
        "bank": "%d-%m-%Y",
        "ledger": "%d/%m/%Y",
    }
    return datetime.strptime(raw, formats[source]).date() 
def normalise(records,source,amount_field,date_field):
    for r in records:
        r["_amount"]=parse_amount(r[amount_field])
        r["_date"]=parse_date(r[date_field],source)
        r["_source"]=source
    return records
def build_index(records):
    index=defaultdict(list)
    for r in records:
        index[(r["_amount"],r["_date"])].append(r)
    return index
def match_pair(records_a,records_b):
    index_b=build_index(records_b)
    matched_pairs=[]
    leftover_a=[]
    for record in records_a:
        key=(record["_amount"],record["_date"])
        candidates=index_b.get(key)
        if candidates:
            matched_pairs.append((record,candidates.pop(0)))
            if not candidates:
                del index_b[key]
        else:
            leftover_a.append(record)
    leftover_b=[r for bucket in index_b.values() for r in bucket]
    return matched_pairs,leftover_a,leftover_b
def match_pair_with_date_tolerance(records_a, records_b, date_tolerance_days=3):
    index_by_amount = defaultdict(list)
    for r in records_b:
        index_by_amount[r["_amount"]].append(r)

    matched_pairs = []
    leftover_a = []

    for record in records_a:
        candidates = index_by_amount.get(record["_amount"], [])
        best_match = None
        best_date_gap = None

        for candidate in candidates:
            gap = abs((candidate["_date"] - record["_date"]).days)
            if gap <= date_tolerance_days:
                if best_date_gap is None or gap < best_date_gap:
                    best_match = candidate
                    best_date_gap = gap

        if best_match is not None:
            matched_pairs.append((record, best_match))
            index_by_amount[record["_amount"]].remove(best_match)
        else:
            leftover_a.append(record)

    leftover_b = [r for bucket in index_by_amount.values() for r in bucket]

    return matched_pairs, leftover_a, leftover_b
GATEWAY_FEE_RATES = {
    "CARD": 0.02,
    "UPI": 0.012,
    "NETBANKING": 0.012,
    "WALLET": 0.012,
}
GST_RATE = 0.18
COMMISSION_RATE = 0.10
TDS_RATE = 0.01


def expected_settlement(gross_amount, payment_method):
    fee_rate = GATEWAY_FEE_RATES[payment_method]
    gateway_fee = round(gross_amount * fee_rate, 2)
    gst_on_fee = round(gateway_fee * GST_RATE, 2)
    commission = round(gross_amount * COMMISSION_RATE, 2)
    tds = round(gross_amount * TDS_RATE, 2)
    net = round(gross_amount - gateway_fee - gst_on_fee - commission - tds, 2)

    return {
        "gateway_fee": gateway_fee,
        "gst_on_fee": gst_on_fee,
        "commission": commission,
        "tds": tds,
        "expected_net": net,
    }


def diagnose_settlement_gap(gross_amount, payment_method, actual_credit, tolerance=0.5):
    breakdown = expected_settlement(gross_amount, payment_method)
    gap = round(breakdown["expected_net"] - actual_credit, 2)

    if abs(gap) <= tolerance:
        return {"status": "correct", "gap": gap, "breakdown": breakdown}

    if abs(gap - breakdown["tds"]) <= tolerance:
        reason = "likely TDS deducted twice"
    elif abs(gap + breakdown["tds"]) <= tolerance:
        reason = "TDS appears to be missing entirely"
    elif abs(gap + breakdown["commission"]) <= tolerance:
        reason = "platform commission appears to be missing"
    else:
        wrong_gst = round(gross_amount * GST_RATE, 2)
        gst_gap = round(wrong_gst - breakdown["gst_on_fee"], 2)
        if abs(gap - gst_gap) <= tolerance:
            reason = "GST appears to have been calculated on the gross amount instead of just the fee"
        else:
            reason = "unexplained settlement gap - does not match a known fee-calculation pattern"

    return {"status": "mismatch", "gap": gap, "reason": reason, "breakdown": breakdown}
import json as _json

with open("config.json") as _f:
    _config = _json.load(_f)

GATEWAY_FEE_RATES = _config["fee_config"]["gateway_fee_rates"]
GST_RATE = _config["fee_config"]["gst_rate"]
COMMISSION_RATE = _config["fee_config"]["commission_rate"]
TDS_RATE = _config["fee_config"]["tds_rate"]

def expected_settlement(gross_amount, payment_method):
    fee_rate = GATEWAY_FEE_RATES[payment_method]
    gateway_fee = round(gross_amount * fee_rate, 2)
    gst_on_fee = round(gateway_fee * GST_RATE, 2)
    commission = round(gross_amount * COMMISSION_RATE, 2)
    tds = round(gross_amount * TDS_RATE, 2)
    net = round(gross_amount - gateway_fee - gst_on_fee - commission - tds, 2)

    return {
        "gateway_fee": gateway_fee,
        "gst_on_fee": gst_on_fee,
        "commission": commission,
        "tds": tds,
        "expected_net": net,
    }


def diagnose_settlement_gap(gross_amount, payment_method, actual_credit, tolerance=0.5):
    breakdown = expected_settlement(gross_amount, payment_method)
    gap = round(breakdown["expected_net"] - actual_credit, 2)

    if abs(gap) <= tolerance:
        return {"status": "correct", "gap": gap, "breakdown": breakdown}

    if abs(gap - breakdown["tds"]) <= tolerance:
        reason = "likely TDS deducted twice"
    elif abs(gap + breakdown["tds"]) <= tolerance:
        reason = "TDS appears to be missing entirely"
    elif abs(gap + breakdown["commission"]) <= tolerance:
        reason = "platform commission appears to be missing"
    else:
        wrong_gst = round(gross_amount * GST_RATE, 2)
        gst_gap = round(wrong_gst - breakdown["gst_on_fee"], 2)
        if abs(gap - gst_gap) <= tolerance:
            reason = "GST appears to have been calculated on the gross amount instead of just the fee"
        else:
            reason = "unexplained settlement gap - does not match a known fee-calculation pattern"

    return {"status": "mismatch", "gap": gap, "reason": reason, "breakdown": breakdown}


def match_gateway_to_bank(gateway_records, bank_records, date_tolerance_days=3):
    matched = []
    leftover_gateway = []
    used_bank_indices = set()

    for g in gateway_records:
        # if the payment method itself is missing (a real data-quality
        # issue introduced by the missing_field distortion), we can't
        # reconstruct the fee waterfall at all - correctly push this to
        # leftover instead of guessing or crashing
        if not g["method"]:
            leftover_gateway.append(g)
            continue

        expected = expected_settlement(g["_amount"], g["method"])["expected_net"]

        best_match = None
        best_index = None
        best_gap = None

        for i, b in enumerate(bank_records):
            if i in used_bank_indices:
                continue
            if abs((b["_date"] - g["_date"]).days) > date_tolerance_days:
                continue

            gap = abs(expected - b["_amount"])
            if gap <= expected * 0.25:
                if best_gap is None or gap < best_gap:
                    best_match = b
                    best_index = i
                    best_gap = gap

        if best_match is not None:
            diagnosis = diagnose_settlement_gap(g["_amount"], g["method"], best_match["_amount"])
            matched.append((g, best_match, diagnosis))
            used_bank_indices.add(best_index)
        else:
            leftover_gateway.append(g)

    leftover_bank = [b for i, b in enumerate(bank_records) if i not in used_bank_indices]

    return matched, leftover_gateway, leftover_bank
    
   