"""
Generates synthetic reconciliation data for three sources that a real
payments company would actually have to reconcile against each other:

  payment_gateway.csv  -> what the gateway logged when the payment happened
  bank_statement.csv   -> what actually shows up in the bank account
  merchant_ledger.csv  -> what the merchant's own books recorded

These three should describe the same underlying transactions, but in
practice they never line up cleanly - different formats, small amount
differences, missing fields, and sometimes a transaction just doesn't
make it into one of the systems at all. That's the whole point of this
dataset: give the matching engine something realistically messy to work
with, and keep a hidden answer key (truth.json) so we can actually score
how well it did.

truth.json should NEVER be read by the matching engine. It only exists
so report/metrics.py can grade the output at the end.
"""

import csv
import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

random.seed(42)  # keeps the dataset reproducible run to run

NUM_TRANSACTIONS = 60
OUTPUT_DIR = Path(".")

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

# content-level distortions - these get rolled independently per source,
# so it's possible for the SAME transaction to look clean in the gateway
# but have a typo'd merchant name in the bank statement. that's realistic
# and it's also what actually forces the matcher to work for its answer.
CONTENT_DISTORTIONS = ["clean", "vendor_variation", "amount_mismatch", "date_mismatch", "missing_field"]
CONTENT_WEIGHTS = [0.55, 0.15, 0.12, 0.12, 0.06]

# structural cases - these change whether/how a transaction appears
# across sources at all, decided once per transaction (not per source)
STRUCTURAL_CASES = ["normal", "orphan", "split"]
STRUCTURAL_WEIGHTS = [0.82, 0.13, 0.05]


def random_amount():
    # most consumer payments cluster around round-ish price points,
    # a smaller chunk are bigger ticket purchases
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


# --- distortion helpers -----------------------------------------------

VENDOR_VARIATIONS = {
    "Myntra": ["MYNTRA", "Myntra Online", "Myntra Online Pvt Ltd", "RAZORPAY*Myntra"],
    "Swiggy": ["SWIGGY", "Swiggy India", "Swiggy Pvt Ltd", "RAZORPAY*SWIGGY"],
    "Zomato": ["ZOMATO", "Zomato Ltd", "Zomato India", "RAZORPAY*ZOMATO"],
    "Flipkart": ["FLIPKART", "Flipkart Internet", "Flipkart Online", "RAZORPAY*FLIPKART"],
}


def vendor_variation(merchant):
    if merchant in VENDOR_VARIATIONS:
        return random.choice(VENDOR_VARIATIONS[merchant])
    # for merchants without a curated list, fall back to something generic
    return random.choice([merchant.upper(), f"{merchant} Online", f"{merchant} Pvt Ltd", f"RAZORPAY*{merchant}"])


def amount_variation(amount):
    # small settlement/rounding style differences, not wild swings
    difference = random.choice([-1, 1, -2, 2, -0.5, 0.5, -10, 10])
    return round(max(1, amount + difference), 2)


def date_variation(date):
    # bank settlement usually lags the actual payment by a day or two
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
    """Takes a clean transaction dict and returns a distorted COPY.
    Doesn't touch the original - each source needs to be able to distort
    independently without affecting what the other sources see."""

    result = transaction.copy()

    if distortion == "clean":
        return result

    if distortion == "vendor_variation":
        result["merchant"] = vendor_variation(transaction["merchant"])

    elif distortion == "amount_mismatch":
        result["amount"] = amount_variation(transaction["amount"])

    elif distortion == "date_mismatch":
        original_date = datetime.strptime(transaction["date"], "%Y-%m-%d")
        result["date"] = date_variation(original_date).strftime("%Y-%m-%d")

    elif distortion == "missing_field":
        field = random.choice(["customer_email", "upi_reference", "payment_method", "merchant"])
        result[field] = ""

    return result


# --- building the ground truth ------------------------------------------

def create_ground_truth():
    transactions = []

    for i in range(NUM_TRANSACTIONS):
        customer = random_customer()
        transactions.append({
            "transaction_id": f"txn_{i + 1:04d}",
            "payment_id": random_id("pay", 10),
            "order_id": random_id("order", 7),
            "merchant": random.choice(MERCHANTS),
            "customer_name": customer["name"],
            "customer_email": customer["email"],
            "amount": random_amount(),
            "currency": "INR",
            "payment_method": random.choice(PAYMENT_METHODS),
            "status": random.choice(STATUSES),
            "date": random_date().strftime("%Y-%m-%d"),
            "upi_reference": generate_upi_reference(),
        })

    return transactions


def pick_structural_case(count):
    """Same trick as before - pre-build the exact list of cases in the
    right proportions and shuffle it, instead of rolling dice per
    transaction. With only 60 records, independent random rolls can
    drift pretty far from the stated percentages, and we want to be
    able to say 'we planted exactly 8 orphans' in the README with a
    straight face."""

    counts = {case: round(count * w) for case, w in zip(STRUCTURAL_CASES, STRUCTURAL_WEIGHTS)}
    cases = []
    for case, n in counts.items():
        cases += [case] * n
    while len(cases) < count:
        cases.append("normal")
    cases = cases[:count]
    random.shuffle(cases)
    return cases


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


def build_bank_row(txn, amount_override=None):
    d = apply_content_distortion(txn, random.choices(CONTENT_DISTORTIONS, weights=CONTENT_WEIGHTS)[0])
    amount = amount_override if amount_override is not None else d["amount"]
    return {
        "txn_id": random_id("BNK", 8),
        "value_date": format_date(datetime.strptime(d["date"], "%Y-%m-%d"), "bank"),
        "description": f"RAZORPAY*{d['merchant']}",
        "credit": format_amount(amount, "bank"),
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

    structural_cases = pick_structural_case(len(transactions))

    for txn, case in zip(transactions, structural_cases):

        entry = {
            "transaction_id": txn["transaction_id"],
            "case_type": case,
            "ground_truth": {
                "merchant": txn["merchant"],
                "amount": txn["amount"],
                "date": txn["date"],
                "payment_method": txn["payment_method"],
                "status": txn["status"],
            },
            "appears_in": [],
        }

        if case == "orphan":
            # transaction shows up in the gateway (it happened, after all)
            # but got dropped somewhere downstream - either it never hit
            # the bank statement yet, or it never got logged in the ledger.
            # this is genuinely common in the real world and it's the
            # thing our matcher needs to correctly leave unmatched rather
            # than force onto the nearest lookalike record.
            missing_from = random.choice(["bank", "ledger"])

            gateway_records.append(build_gateway_row(txn))
            entry["appears_in"].append("gateway")

            if missing_from != "bank":
                bank_records.append(build_bank_row(txn))
                entry["appears_in"].append("bank")

            if missing_from != "ledger":
                ledger_records.append(build_ledger_row(txn))
                entry["appears_in"].append("ledger")

            entry["missing_from"] = missing_from

        elif case == "split":
            # settlement sometimes breaks one payment into two bank
            # entries (e.g. a partial refund netted off, or a payout
            # split across two batches). ledger and gateway still show
            # it as a single transaction.
            gateway_records.append(build_gateway_row(txn))
            ledger_records.append(build_ledger_row(txn))

            part_one = round(txn["amount"] * random.uniform(0.3, 0.7), 2)
            part_two = round(txn["amount"] - part_one, 2)
            bank_records.append(build_bank_row(txn, amount_override=part_one))
            bank_records.append(build_bank_row(txn, amount_override=part_two))

            entry["appears_in"] = ["gateway", "ledger", "bank(x2 split)"]

        else:  # normal
            gateway_records.append(build_gateway_row(txn))
            bank_records.append(build_bank_row(txn))
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
    with open(OUTPUT_DIR / "truth.json", "w", encoding="utf-8") as f:
        json.dump(truth, f, indent=2)


def main():
    print("Generating synthetic payment reconciliation data...")

    transactions = create_ground_truth()
    gateway, bank, ledger, truth = create_source_records(transactions)

    write_csv("payment_gateway.csv", gateway)
    write_csv("bank_statement.csv", bank)
    write_csv("merchant_ledger.csv", ledger)
    write_truth(truth)

    case_counts = {}
    for entry in truth:
        case_counts[entry["case_type"]] = case_counts.get(entry["case_type"], 0) + 1

    print()
    print(f"Generated {len(transactions)} ground-truth transactions.")
    print(f"Case breakdown: {case_counts}")
    print(f"Gateway records: {len(gateway)} | Bank records: {len(bank)} | Ledger records: {len(ledger)}")
    print()
    print("Files created: payment_gateway.csv, bank_statement.csv, merchant_ledger.csv, truth.json")
    print("Reminder: the matching engine should only read the three CSVs above, never truth.json.")


if __name__ == "__main__":
    main()