def build_final_report(gateway, ledger_matched, ledger_leftover_gateway,
                        bank_matched, bank_leftover_gateway):

    ledger_matches_by_payment_id = {g["payment_id"]: l for g, l in ledger_matched}
    bank_matches_by_payment_id = {g["payment_id"]: (b, diag) for g, b, diag in bank_matched}
    bank_leftover_ids = {g["payment_id"] for g in bank_leftover_gateway}

    report = []

    for g in gateway:
        pid = g["payment_id"]
        has_ledger_match = pid in ledger_matches_by_payment_id
        has_bank_match = pid in bank_matches_by_payment_id

        entry = {
            "payment_id": pid,
            "merchant": g["merchant"],
            "gross_amount": g["_amount"],
            "date": str(g["_date"]),
        }

        if has_ledger_match and has_bank_match:
            bank_record, diagnosis = bank_matches_by_payment_id[pid]
            if diagnosis["status"] == "correct":
                entry["verdict"] = "fully_reconciled"
            else:
                entry["verdict"] = "settlement_issue"
                entry["reason"] = diagnosis["reason"]
                entry["gap"] = diagnosis["gap"]

        elif has_bank_match and not has_ledger_match:
            entry["verdict"] = "ledger_missing"

        elif has_ledger_match and not has_bank_match:
            entry["verdict"] = "bank_missing"
            if pid in bank_leftover_ids and not g["method"]:
                entry["reason"] = "payment method missing - cannot verify settlement"

        else:
            entry["verdict"] = "unresolved"

        report.append(entry)

    return report


def summarize(report):
    counts = {}
    for entry in report:
        counts[entry["verdict"]] = counts.get(entry["verdict"], 0) + 1
    return counts