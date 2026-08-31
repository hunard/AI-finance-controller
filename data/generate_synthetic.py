"""
Generates synthetic reconciliation data modeling a Razorpay Route-style
marketplace settlement flow, not just generic three-source matching.

The real problem this models (sourced from Razorpay's own product docs
and merchant-facing guidance): when a marketplace uses Route to split
customer payments across sellers, what a seller actually receives isn't
just "the sale amount" - it's the output of a deduction chain:

    gross payment
      - gateway fee (varies by payment method)
      - GST on that fee (18%, mandatory)
      - platform commission
      - TDS under Section 194-O (1%, mandatory for e-commerce sellers)
      = net settlement actually paid out

If any one step in that chain is calculated wrong - TDS deducted twice,
GST accidentally applied to the gross amount instead of just the fee,
commission forgotten - the seller's payout will be off, and a normal
"does amount X equal amount Y" matcher has no way to explain why, because
it doesn't know there's a formula behind the number at all.

This generator produces:
  payment_gateway.csv  -> gross amount charged to the customer
  bank_statement.csv   -> what actually got paid out (sometimes correct,
                           sometimes with a specific, realistic fee
                           miscalculation baked in)
  merchant_ledger.csv  -> the merchant's own record of the sale

truth.json holds the full expected fee breakdown per transaction, and is
kept out of version control - the matching engine should reconstruct the
expected settlement itself, not read the answer key.
"""

import csv
import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)

NUM_TRANSACTIONS = 60
OUTPUT_DIR = Path(".")
GROUND_TRUTH_DIR = Path("data/ground_truth")

MERCHANTS = [
    "Myntra", "Swiggy", "Zomato", "Flipkart", "Zepto", "Blinkit",
    "BookMyShow", "Nykaa", "Meesho", "AJIO", "Amazon", "MakeMyTrip",
    "Urban Company", "CRED", "Cult.fit",
]

CUSTOMERS = [
    ("Aarav", "Mehta"), ("Ananya", "Sharma"), ("Rohan", "Patel"),
    ("Priya", "Nair"), ("Aditya", "Rao"), ("Kavya", "Iyer"),
    ("Arjun", "Malhotra"), ("Sneha", "Kapoor"), ("Rahul", "Verma"),
    ("Ishita", "Gupta"), ("Dev", "Shah"), ("Meera", "Joshi"),
]

PAYMENT_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
STATUSES = ["captured", "captured", "captured", "captured", "refunded", "failed"]

GATEWAY_FEE_RATES = {
    "CARD": 0.02,
    "UPI": 0.012,
    "NETBANKING": 0.012,
    "WALLET": 0.012,
}

GST_RATE = 0.18
COMMISSION_RATE = 0.10
TDS_RATE = 0.01

CONTENT_DISTORTIONS = ["clean", "vendor_variation", "date_mismatch", "missing_field"]
CONTENT_WEIGHTS = [0.65, 0.15, 0.14, 0.06]

STRUCTURAL_CASES = ["normal", "orphan", "split"]
STRUCTURAL_WEIGHTS = [0.82, 0.13, 0.05]

FEE_CASES = ["correct", "tds_double_deducted", "gst_on_gross", "commission_missing", "tds_missing"]
FEE_WEIGHTS = [0.70, 0.08, 0.08, 0.07, 0.07]


def random_amount():
    common_amounts = [199, 249, 299, 349, 399, 499, 599, 799, 999,
                       1299, 1499, 1999, 2499, 2999, 4999]
    if random.random() < 0.8:
        return float(random.choice(common_amounts))
    return round(random.uniform(5000, 25000), 2)


def random_customer():
    first, last = random.choice(CUSTOMERS)
    email = f"{first.lower()}.{last.lower()}{random.randint(10, 99)}@example.com"
    return {"name": f"{first} {last}", "email": email}


def random_date():
    start = datetime(2026, 8, 1)
    end = datetime(2026, 8, 22)
    days = (end - start).days
    return start + timedelta(days=random.randint(0, days))


def random_id(prefix, length=8):
    chars = string.ascii_letters + string.digits
    value = "".join(random.choices(chars, k=length))
    return f"{prefix}_{value}"


def generate_upi_reference():
    return str(random.randint(1000000000, 9999999999))


def compute_settlement(gross_amount, payment_method):
    fee_rate = GATEWAY_FEE_RATES[payment_method]
    gateway_fee = round(gross_amount * fee_rate, 2)
    gst_on_fee = round(gateway_fee * GST_RATE, 2)
    commission = round(gross_amount * COMMISSION_RATE, 2)
    tds = round(gross_amount * TDS_RATE, 2)
    net_settlement = round(gross_amount - gateway_fee - gst_on_fee - commission - tds, 2)

    return {
        "gateway_fee": gateway_fee,
        "gst_on_fee": gst_on_fee,
        "commission": commission,
        "tds": tds,
        "expected_net_settlement": net_settlement,
    }


def apply_fee_case(breakdown, fee_case):
    correct = breakdown["expected_net_settlement"]

    if fee_case == "correct":
        return correct
    if fee_case == "tds_double_deducted":
        return round(correct - breakdown["tds"], 2)
    if fee_case == "gst_on_gross":
        return correct
    if fee_case == "commission_missing":
        return round(correct + breakdown["commission"], 2)
    if fee_case == "tds_missing":
        return round(correct + breakdown["tds"], 2)

    return correct


VENDOR_VARIATIONS = {
    "Myntra": ["MYNTRA", "Myntra Online", "Myntra Online Pvt Ltd", "RAZORPAY*Myntra"],
    "Swiggy": ["SWIGGY", "Swiggy India", "Swiggy Pvt Ltd", "RAZORPAY*SWIGGY"],
    "Zomato": ["ZOMATO", "Zomato Ltd", "Zomato India", "RAZORPAY*ZOMATO"],
    "Flipkart": ["FLIPKART", "Flipkart Internet", "Flipkart Online", "RAZORPAY*FLIPKART"],
}


def vendor_variation(merchant):
    if merchant in VENDOR_VARIATIONS:
        return random.choice(VENDOR_VARIATIONS[merchant])
    return random.choice([merchant.upper(), f"{merchant} Online", f"{merchant} Pvt Ltd", f"RAZORPAY*{merchant}"])


def date_variation(date):
    offset = random.choice([-1, 1, 1, 2])
    return date + timedelta(days=offset)


def format_date(date, source):
    if source == "gateway":
        return date.strftime("%Y-%m-%d %H:%M:%S")
    if source == "bank":
        return date.strftime("%d-%m-%Y")
    if source == "ledger":
        return date.strftime("%d/%m/%Y")
    return date.strftime("%Y-%m-%d")


def format_amount(amount, source):
    if source == "gateway":
        return f"{amount:.2f}"
    if source == "bank":
        return f"{amount:,.2f}"
    if source == "ledger":
        return f"{amount:.0f}"
    return str(amount)


def apply_content_distortion(transaction, distortion):
    result = transaction.copy()

    if distortion == "clean":
        return result
    if distortion == "vendor_variation":
        result["merchant"] = vendor_variation(transaction["merchant"])
    elif distortion == "date_mismatch":
        original_date = datetime.strptime(transaction["date"], "%Y-%m-%d")
        result["date"] = date_variation(original_date).strftime("%Y-%m-%d")
    elif distortion == "missing_field":
        field = random.choice(["customer_email", "upi_reference", "payment_method", "merchant"])
        result[field] = ""

    return result


def create_ground_truth():
    transactions = []
    for i in range(NUM_TRANSACTIONS):
        customer = random_customer()
        method = random.choice(PAYMENT_METHODS)
        amount = random_amount()
        breakdown = compute_settlement(amount, method)

        transactions.append({
            "transaction_id": f"txn_{i + 1:04d}",
            "payment_id": random_id("pay", 10),
            "order_id": random_id("order", 7),
            "merchant": random.choice(MERCHANTS),
            "customer_name": customer["name"],
            "customer_email": customer["email"],
            "amount": amount,
            "currency": "INR",
            "payment_method": method,
            "status": random.choice(STATUSES),
            "date": random_date().strftime("%Y-%m-%d"),
            "upi_reference": generate_upi_reference(),
            "fee_breakdown": breakdown,
        })

    return transactions


def pick_weighted_list(options, weights, count):
    counts = {opt: round(count * w) for opt, w in zip(options, weights)}
    items = []
    for opt, n in counts.items():
        items += [opt] * n
    while len(items) < count:
        items.append(options[0])
    items = items[:count]
    random.shuffle(items)
    return items


def build_gateway_row(txn):
    d = apply_content_distortion(txn, random.choices(CONTENT_DISTORTIONS, weights=CONTENT_WEIGHTS)[0])
    return {
        "payment_id": txn["payment_id"],
        "order_id": txn["order_id"],
        "created_at": format_date(datetime.strptime(d["date"], "%Y-%m-%d"), "gateway"),
        "amount": format_amount(d["amount"], "gateway"),
        "currency": d["currency"],
        "method": d["payment_method"],
        "status": d["status"],
        "customer_email": d["customer_email"],
        "merchant": d["merchant"],
    }


def build_bank_row(txn, settled_amount):
    d = apply_content_distortion(txn, random.choices(CONTENT_DISTORTIONS, weights=CONTENT_WEIGHTS)[0])
    return {
        "txn_id": random_id("BNK", 8),
        "value_date": format_date(datetime.strptime(d["date"], "%Y-%m-%d"), "bank"),
        "description": f"RAZORPAY*{d['merchant']}",
        "credit": format_amount(settled_amount, "bank"),
        "debit": "",
        "reference": f"RPAY{d['upi_reference']}" if d["upi_reference"] else "",
    }


def build_ledger_row(txn):
    d = apply_content_distortion(txn, random.choices(CONTENT_DISTORTIONS, weights=CONTENT_WEIGHTS)[0])
    return {
        "entry_id": random_id("LED", 8),
        "entry_date": format_date(datetime.strptime(d["date"], "%Y-%m-%d"), "ledger"),
        "account": f"Sales - {d['merchant']}",
        "description": f"{d['merchant']} Order {txn['order_id']}",
        "debit": "",
        "credit": format_amount(d["amount"], "ledger"),
        "reference": txn["order_id"],
    }


def create_source_records(transactions):
    gateway_records, bank_records, ledger_records = [], [], []
    truth = []

    structural_cases = pick_weighted_list(STRUCTURAL_CASES, STRUCTURAL_WEIGHTS, len(transactions))
    fee_cases = pick_weighted_list(FEE_CASES, FEE_WEIGHTS, len(transactions))

    for txn, case, fee_case in zip(transactions, structural_cases, fee_cases):

        breakdown = txn["fee_breakdown"]

        if fee_case == "gst_on_gross":
            wrong_gst = round(txn["amount"] * GST_RATE, 2)
            settled_amount = round(
                txn["amount"] - breakdown["gateway_fee"] - wrong_gst
                - breakdown["commission"] - breakdown["tds"], 2
            )
        else:
            settled_amount = apply_fee_case(breakdown, fee_case)

        entry = {
            "transaction_id": txn["transaction_id"],
            "payment_id": txn["payment_id"],
            "case_type": case,
            "fee_case": fee_case,
            "ground_truth": {
                "merchant": txn["merchant"],
                "gross_amount": txn["amount"],
                "date": txn["date"],
                "payment_method": txn["payment_method"],
                "status": txn["status"],
            },
            "fee_breakdown": breakdown,
            "actual_settled_amount": settled_amount,
            "appears_in": [],
        }

        if case == "orphan":
            missing_from = random.choice(["bank", "ledger"])
            gateway_records.append(build_gateway_row(txn))
            entry["appears_in"].append("gateway")
            if missing_from != "bank":
                bank_records.append(build_bank_row(txn, settled_amount))
                entry["appears_in"].append("bank")
            if missing_from != "ledger":
                ledger_records.append(build_ledger_row(txn))
                entry["appears_in"].append("ledger")
            entry["missing_from"] = missing_from

        elif case == "split":
            gateway_records.append(build_gateway_row(txn))
            ledger_records.append(build_ledger_row(txn))
            part_one = round(settled_amount * random.uniform(0.3, 0.7), 2)
            part_two = round(settled_amount - part_one, 2)
            bank_records.append(build_bank_row(txn, part_one))
            bank_records.append(build_bank_row(txn, part_two))
            entry["appears_in"] = ["gateway", "ledger", "bank(x2 split)"]

        else:
            gateway_records.append(build_gateway_row(txn))
            bank_records.append(build_bank_row(txn, settled_amount))
            ledger_records.append(build_ledger_row(txn))
            entry["appears_in"] = ["gateway", "bank", "ledger"]

        truth.append(entry)

    return gateway_records, bank_records, ledger_records, truth


def write_csv(filename, records):
    if not records:
        return
    with open(OUTPUT_DIR / filename, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)


def write_truth(truth):
    GROUND_TRUTH_DIR.mkdir(parents=True, exist_ok=True)
    with open(GROUND_TRUTH_DIR / "truth.json", "w", encoding="utf-8") as f:
        json.dump(truth, f, indent=2)


def main():
    print("Generating Razorpay-style settlement reconciliation data...")

    transactions = create_ground_truth()
    gateway, bank, ledger, truth = create_source_records(transactions)

    write_csv("payment_gateway.csv", gateway)
    write_csv("bank_statement.csv", bank)
    write_csv("merchant_ledger.csv", ledger)
    write_truth(truth)

    case_counts = {}
    fee_counts = {}
    for entry in truth:
        case_counts[entry["case_type"]] = case_counts.get(entry["case_type"], 0) + 1
        fee_counts[entry["fee_case"]] = fee_counts.get(entry["fee_case"], 0) + 1

    print()
    print(f"Generated {len(transactions)} ground-truth transactions.")
    print(f"Structural case breakdown: {case_counts}")
    print(f"Fee/settlement case breakdown: {fee_counts}")
    print(f"Gateway records: {len(gateway)} | Bank records: {len(bank)} | Ledger records: {len(ledger)}")
    print()
    print("Files created: payment_gateway.csv, bank_statement.csv, merchant_ledger.csv, data/ground_truth/truth.json")


if __name__ == "__main__":
    main()