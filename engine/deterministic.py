import csv
from pathlib import Path
from datetime import datetime
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
   
    
   