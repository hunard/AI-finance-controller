import json


def load_truth(path="data/ground_truth/truth.json"):
    with open(path) as f:
        return {entry["payment_id"]: entry for entry in json.load(f)}


def expected_verdict(truth_entry):
    case_type = truth_entry["case_type"]

    if case_type == "orphan":
        missing = truth_entry.get("missing_from")
        return "bank_missing" if missing == "bank" else "ledger_missing"

    if case_type == "split":
        return "split_not_yet_handled"

    if truth_entry["fee_case"] == "correct":
        return "fully_reconciled"
    else:
        return "settlement_issue"


FEE_CASE_TO_REASON_KEYWORD = {
    "tds_double_deducted": "twice",
    "tds_missing": "TDS appears to be missing",
    "commission_missing": "commission appears to be missing",
    "gst_on_gross": "GST appears to have been calculated on the gross",
}


def score(report, truth_by_payment_id):
    results = {
        "correct_verdict": 0,
        "wrong_verdict": 0,
        "not_scored_split": 0,
        "settlement_diagnosis_correct": 0,
        "settlement_diagnosis_wrong": 0,
    }

    by_case_type = {}
    mismatches = []

    for entry in report:
        pid = entry["payment_id"]
        truth_entry = truth_by_payment_id.get(pid)
        if truth_entry is None:
            continue

        case_type = truth_entry["case_type"]
        by_case_type.setdefault(case_type, {"correct": 0, "total": 0})
        by_case_type[case_type]["total"] += 1

        expected = expected_verdict(truth_entry)

        if expected == "split_not_yet_handled":
            results["not_scored_split"] += 1
            continue

        if entry["verdict"] == expected:
            results["correct_verdict"] += 1
            by_case_type[case_type]["correct"] += 1

            if expected == "settlement_issue":
                true_fee_case = truth_entry["fee_case"]
                keyword = FEE_CASE_TO_REASON_KEYWORD.get(true_fee_case, "")
                actual_reason = entry.get("reason", "")
                if keyword and keyword.lower() in actual_reason.lower():
                    results["settlement_diagnosis_correct"] += 1
                else:
                    results["settlement_diagnosis_wrong"] += 1
        else:
            results["wrong_verdict"] += 1
            mismatches.append({
                "payment_id": pid,
                "merchant": entry["merchant"],
                "expected": expected,
                "got": entry["verdict"],
                "case_type": case_type,
                "fee_case": truth_entry.get("fee_case"),
            })

    total_scored = results["correct_verdict"] + results["wrong_verdict"]
    accuracy = round(results["correct_verdict"] / total_scored * 100, 1) if total_scored else 0

    return {
        "overall_accuracy_pct": accuracy,
        "totals": results,
        "by_case_type": by_case_type,
        "mismatches": mismatches,
    }