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
        index[(r["_date"],r["_source"])].append(r)
    return index

   
    
   