#!/usr/bin/env python3
"""
load_telemetry.py - Step 5a: load BMS telemetry into the MongoDB document store.

Source : telemetry_data.json (newline-delimited JSON, one reading per line)
Target : gigavolt_iot.bms_telemetry (database name comes from MONGO_DB)

Why not plain mongoimport (as in the class lab)?
  * timestamp must be a real Date, or time-window queries compare strings
  * model_key links telemetry to the ERP ("Gigavolt Megapack X-7000" -> "X-7000"),
    because telemetry equipment IDs do not match any ERP equipment_id
  * source file + line give every document provenance for citations
  * retrieval needs indexes on timestamp, equipment_id and error codes

The nested telemetry{} object and flagged_components[] array are kept as they are.
log_id is the _id, so a re-run cannot create duplicates.

Usage:
    python load_telemetry.py              # drop, reload, index, verify
    python load_telemetry.py --dry-run    # parse and report only, no database needed
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

DEFAULT_FILE = "/opt/gigavolt/telemetry/telemetry_data.json"
COLLECTION = "bms_telemetry"
MODEL_RE = re.compile(r"\b([A-Z]-\d{3,5})\b")
REQUIRED = ("log_id", "timestamp", "equipment_id", "model")

# (name, keys): each one backs a retrieval pattern used by the document retriever
INDEXES = [
    ("idx_timestamp", [("timestamp", -1)]),
    ("idx_equipment_time", [("equipment_id", 1), ("timestamp", -1)]),
    ("idx_fault_time", [("fault_code", 1), ("timestamp", -1)]),
    ("idx_model_fault_time", [("model_key", 1), ("fault_code", 1), ("timestamp", -1)]),
    ("idx_flagged_components", [("flagged_components", 1)]),
]


def model_key(raw):
    """'Gigavolt Megapack X-7000' -> 'X-7000'; None if no model number is present."""
    match = MODEL_RE.search(raw or "")
    return match.group(1) if match else None


def parse_timestamp(value):
    """'2024-09-28T16:00:00.000Z' -> timezone-aware datetime (raises ValueError if invalid)."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_document(record, line_no, source_file):
    """Transform one raw reading. Raises ValueError with a readable reason if it is unusable."""
    missing = [f for f in REQUIRED if not record.get(f)]
    if missing:
        raise ValueError(f"missing {', '.join(missing)}")
    doc = dict(record)
    doc["_id"] = record["log_id"]
    doc["timestamp"] = parse_timestamp(record["timestamp"])
    doc["model_key"] = model_key(record["model"])
    doc["source"] = {"file": source_file, "line": line_no}
    return doc


def read_documents(path):
    """Returns (documents, errors). Bad or duplicate lines are reported and skipped, never fatal."""
    docs, errors, seen = [], [], set()
    name = Path(path).name
    with open(path, encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                doc = to_document(json.loads(line), line_no, name)
            except (ValueError, TypeError, AttributeError) as exc:
                errors.append(f"line {line_no}: {exc}")
                continue
            if doc["_id"] in seen:
                errors.append(f"line {line_no}: duplicate log_id {doc['_id']}")
                continue
            seen.add(doc["_id"])
            docs.append(doc)
    return docs, errors


def summarize(docs):
    print(f"Documents       : {len(docs)}")
    print(f"Equipment IDs   : {len({d['equipment_id'] for d in docs})}")
    print(f"Models          : {dict(Counter(d['model_key'] for d in docs))}")
    print(f"Fault readings  : {sum(1 for d in docs if d.get('fault_code'))}")
    print(f"Distinct faults : {len({d['fault_code'] for d in docs if d.get('fault_code')})}")
    print(f"Time range      : {min(d['timestamp'] for d in docs)} -> {max(d['timestamp'] for d in docs)}")


def verify_indexes(col, docs):
    """Runs one query per required index and confirms MongoDB chooses an index scan."""
    sample = next(d for d in docs if d.get("fault_code"))
    checks = [
        ("timestamp", {"timestamp": {"$gte": sample["timestamp"]}}),
        ("equipment_id", {"equipment_id": sample["equipment_id"]}),
        ("fault_code", {"fault_code": sample["fault_code"]}),
        ("model + fault", {"model_key": sample["model_key"], "fault_code": sample["fault_code"]}),
    ]
    ok = True
    for label, query in checks:
        plan = col.find(query).explain()["queryPlanner"]["winningPlan"]
        uses_index = "IXSCAN" in json.dumps(plan, default=str)
        ok = ok and uses_index
        matched = col.count_documents(query)
        print(f"  {label:<14} {'IXSCAN' if uses_index else 'NO INDEX':<9} {matched} matching documents")
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=DEFAULT_FILE)
    ap.add_argument("--dry-run", action="store_true", help="parse and report only")
    args = ap.parse_args()

    docs, errors = read_documents(args.file)
    for err in errors:
        print(f"SKIPPED {err}", file=sys.stderr)
    if not docs:
        sys.exit("No usable documents found.")
    summarize(docs)
    if args.dry_run:
        print(f"Dry run: nothing written. Skipped lines: {len(errors)}")
        return

    from pymongo import MongoClient

    client = MongoClient(os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"),
                         serverSelectionTimeoutMS=5000)
    col = client[os.environ.get("MONGO_DB", "gigavolt_iot")][COLLECTION]
    col.drop()
    col.insert_many(docs)
    for name, keys in INDEXES:
        col.create_index(keys, name=name)

    stored = col.count_documents({})
    print(f"\nInserted {stored} documents into {col.full_name}; skipped lines: {len(errors)}")
    print(f"Indexes: {sorted(col.index_information())}")
    print("Index check:")
    indexes_ok = verify_indexes(col, docs)

    critical = col.find_one({"status": "CRITICAL_FAULT"}, sort=[("timestamp", 1)])
    if critical:
        print(f"\nSample document:\n{json.dumps(critical, indent=2, default=str)}")

    if stored != len(docs) or not indexes_ok:
        sys.exit("VERIFICATION FAILED: see the counts and index check above.")
    print("\nVerification passed.")


if __name__ == "__main__":
    main()
