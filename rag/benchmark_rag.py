#!/usr/bin/env python3
"""
benchmark_rag.py - Runs the test questions and writes the latency and provenance evidence.

Outputs in /opt/gigavolt/results:
    latency.csv         per-question timing for every pipeline stage
    latency_report.md   P50 / P95 / P99 per stage against the 5-second target
    test_results.md     each answer with its source provenance map and verification result

Free-tier rate limits are respected with a pause between questions (--pause). That pause is not
part of any latency figure. Any question that hit a rate limit or LLM error is reported, and its
total is excluded from the percentiles, so a wait is not counted as model speed.

Usage:
    python benchmark_rag.py                # run the question set once
    python benchmark_rag.py --repeat 3     # more samples for the percentiles
"""
import argparse
import csv
import os
from pathlib import Path

import numpy as np

from rag_pipeline import RagPipeline, source_line

OUT = Path(os.environ.get("RAG_RESULTS", "/opt/gigavolt/results"))
STAGES = ["route", "encode", "sql", "vector", "mongo", "retrieve_parallel", "assemble", "generate", "verify", "total"]
TARGET_MS = 5000

QUESTIONS = [
    ("sample query 1", "What are common failure modes for Model X-7000 batteries in high-temperature environments?"),
    ("sample query 2", "Which suppliers provide lithium cells for our commercial energy storage units?"),
    ("sample query 3, not in ERP", "Show me service history for equipment unit SN-4829 and related warranty claims"),
    ("multi-source unit", "Show me the service history and warranty claims for equipment unit {unit}"),
    ("telemetry unit", "What happened to unit SN-X7-0094 and which components were flagged?"),
    ("fault code", "What does fault code ERR_COOL_302 indicate and on which units has it occurred?"),
    ("thermal, model", "How hot do C-1200 units get during thermal faults and what do the manuals advise?"),
    ("procedure", "What is the procedure for filing a field warranty claim?"),
    ("safety", "What should a technician do in a battery fire or thermal runaway emergency?"),
    ("specification", "What are the specifications of the LFP battery cell?"),
    ("warranty aggregate", "What are the most common service resolutions and warranty claim outcomes for X-5000 units?"),
    ("out of scope", "What was Gigavolt's total revenue last quarter?"),
]


def demo_unit(pipeline):
    """A real X-7000 unit with claims, so the demo question draws on all three sources."""
    rows = pipeline.retriever.sql._rows(
        "SELECT eu.equipment_id FROM equipment_units eu JOIN warranty_claims wc ON wc.equipment_id=eu.equipment_id "
        "WHERE eu.model='X-7000' GROUP BY eu.equipment_id ORDER BY COUNT(*) DESC LIMIT 1")
    return rows[0]["equipment_id"] if rows else "EQ-0000"


def percentiles(values):
    p50, p95, p99 = np.percentile(values, [50, 95, 99])
    return p50, p95, p99


def total_time_table(records):
    """Plain table: each question, then its overall time for every run."""
    groups = {}
    for _, record in records:
        groups.setdefault(record["question"], []).append(record["timings_ms"]["total"])
    runs = max(len(totals) for totals in groups.values())
    lines = ["", "## Total time per query", "",
             "| Query | " + " | ".join(f"Run {n} (s)" for n in range(1, runs + 1)) + " |",
             "|---|" + "---:|" * runs]
    for question, totals in groups.items():
        lines.append(f"| {question} | " + " | ".join(f"{total / 1000:.2f}" for total in totals) + " |")
    return lines


def per_question_table(records):
    """One row per question, with each repeat's time separated by a slash."""
    groups = {}
    for category, record in records:
        groups.setdefault(record["question"], (category, []))[1].append(record["timings_ms"])

    def series(runs, stage, scale, digits):
        return " / ".join(f"{run.get(stage, 0) / scale:.{digits}f}" for run in runs)

    lines = ["", "## Latency per question", "",
             "Each value is one run, in run order.", "",
             "| Category | Question | Total (s) | Retrieval (ms) | Gemini (ms) |", "|---|---|---|---|---|"]
    for question, (category, runs) in groups.items():
        lines.append(f"| {category} | {question} | {series(runs, 'total', 1000, 2)} | "
                     f"{series(runs, 'retrieve_parallel', 1, 0)} | {series(runs, 'generate', 1, 0)} |")
    return lines


def write_latency(records):
    with (OUT / "latency.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["category", "question", "backend", "llm_error"] + STAGES + ["rate_limit_wait"])
        for category, record in records:
            timings = record["timings_ms"]
            writer.writerow([category, record["question"], record["backend"], bool(record["llm_error"])]
                            + [round(timings.get(s, 0), 1) for s in STAGES]
                            + [round(timings.get("rate_limit_wait", 0))])

    clean = [record for _, record in records
             if not record["llm_error"] and not record["timings_ms"].get("rate_limit_wait")]
    lines = ["# Latency report", "",
             f"Questions run: {len(records)}. Used for percentiles: {len(clean)} "
             f"(excluded: {len(records) - len(clean)}, rate limit or LLM error).",
             f"Backend: {records[0][1]['backend']}. Stores queried in parallel threads.", ""]
    if clean:
        lines += ["| Stage | P50 (ms) | P95 (ms) | P99 (ms) | Samples |", "|---|---:|---:|---:|---:|"]
        for stage in STAGES:
            values = [r["timings_ms"][stage] for r in clean if stage in r["timings_ms"]]
            if values:
                p50, p95, p99 = percentiles(values)
                lines.append(f"| {stage} | {p50:.1f} | {p95:.1f} | {p99:.1f} | {len(values)} |")
        totals = [r["timings_ms"]["total"] for r in clean]
        median = np.median(totals)
        lines += ["", f"**End-to-end median: {median / 1000:.2f} s, target under {TARGET_MS / 1000:.0f} s: "
                      f"{'met' if median < TARGET_MS else 'NOT met'}.** "
                      f"Questions over target: {sum(t >= TARGET_MS for t in totals)} of {len(totals)}."]
    lines += total_time_table(records)
    lines += per_question_table(records)
    (OUT / "latency_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return lines


def write_results(records):
    lines = ["# Test query results and provenance map", ""]
    for number, (category, record) in enumerate(records, start=1):
        check = record["verification"]
        lines += [f"## {number}. {record['question']}", "", f"Category: {category}. "
                  f"Total latency: {record['timings_ms']['total'] / 1000:.2f} s. "
                  f"Traceable statements: {check['supported']}/{check['factual']}.", "",
                  "**Answer**", "", record["answer"], "", "**Provenance map**", "",
                  "| Tag | Source record | Cited |", "|---|---|---|"]
        lines += [f"| {s['tag']} | {source_line(s).replace('|', '/')} | {'yes' if s['cited'] else 'no'} |"
                  for s in record["sources"]]
        if check.get("omitted_records"):
            lines += ["", f"Records retrieved but not mentioned: {', '.join(check['omitted_records'])}"]
        problems = [item for item in check["statements"] if item["verdict"] == "problem"]
        if problems:
            lines += ["", "**Statements that failed verification**", ""]
            lines += [f"- {'; '.join(item['problems'])}: {item['statement']}" for item in problems]
        if record["llm_error"]:
            lines += ["", f"LLM error: {record['llm_error']}"]
        if record["store_errors"]:
            lines += ["", f"Store errors: {record['store_errors']}"]
        lines.append("")
    (OUT / "test_results.md").write_text("\n".join(lines), encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--pause", type=float, default=6.0, help="seconds between questions (free-tier rate limit)")
    args = ap.parse_args()

    import time

    OUT.mkdir(parents=True, exist_ok=True)
    pipeline = RagPipeline()
    pipeline.warmup()
    unit = demo_unit(pipeline)
    print(f"Backend: {pipeline.backend.name}; demo unit: {unit}")

    records = []
    for round_number in range(args.repeat):
        for category, question in QUESTIONS:
            record = pipeline.ask(question.format(unit=unit))
            records.append((category, record))
            check = record["verification"]
            status = "LLM ERROR" if record["llm_error"] else f"{check['supported']}/{check['factual']} traceable"
            print(f"[{round_number + 1}] {record['timings_ms']['total'] / 1000:5.2f} s  {status:<18} {category}")
            time.sleep(args.pause)

    summary = write_latency(records)
    write_results(records[:len(QUESTIONS)])
    print("\n" + "\n".join(summary))
    print(f"\nWrote latency.csv, latency_report.md and test_results.md to {OUT}")


if __name__ == "__main__":
    main()
