#!/usr/bin/env python3
"""
demo.py - Live screencast demo. Shows each RAG stage on screen, for any typed question:

    routing -> retrieval per database -> context sent to Gemini -> answer -> verification -> latency

It calls the same functions as rag_pipeline.py, so the demo shows the benchmarked code path.
It pauses between stages for narration. Those pauses are not counted: the reported latency adds up
only the measured pipeline stages.

Usage (from /opt/gigavolt/src, config.env loaded):
    python demo.py              # press Enter to move between stages
    python demo.py --no-pause   # print every stage straight through
    python demo.py --hide-prompt  # skip printing the full prompt sent to Gemini

At the question prompt: type a question, a preset number, 'p' to print the last full prompt, or 'q'.
"""
import argparse
import os
import sys
import textwrap
import time

from hybrid_retrieval import assemble_context
from rag_pipeline import RagPipeline, build_prompt, extractive_verification, source_line, verify_answer

PRESETS = [
    "What are common failure modes for Model X-7000 batteries in high-temperature environments?",
    "Show me the service history and warranty claims for equipment unit EQ-7171",
    "Show me service history for equipment unit SN-4829 and related warranty claims",
    "What was Gigavolt's total revenue last quarter?",
]
STORE_NAMES = {"sql": "MariaDB (SQL)", "mongo": "MongoDB (document)", "vector": "ChromaDB (vector)"}
TARGET_S = 5.0
WIDTH = 100
COLOR = sys.stdout.isatty()


def paint(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def header(number, title):
    print("\n" + paint(f"[{number}] {title}", "1;36"))


def wrapped(text, indent="    "):
    for line in text.splitlines():
        print(textwrap.fill(line, WIDTH, initial_indent=indent, subsequent_indent=indent) if line.strip() else "")


def show_routing(result):
    plan, timings = result.plan, result.timings_ms
    header(1, f"ROUTING: rule-based, no AI ({timings['route']:.1f} ms)")
    found = {"models": plan.models, "units": plan.equipment_ids + plan.serials, "records": plan.dispatch_ids + plan.claim_ids,
             "fault codes": plan.fault_codes}
    intents = [name for name, on in (("failure", plan.wants_failure), ("thermal", plan.wants_thermal),
                                     ("history", plan.wants_history), ("supplier", plan.wants_supplier)) if on]
    print(f"    Found: {({k: v for k, v in found.items() if v}) or 'no identifiers'}; intent: {intents or 'none'}")
    for reason in plan.reasons:
        print(f"    - {reason}")


def show_retrieval(result):
    timings = result.timings_ms
    header(2, f"RETRIEVAL: databases searched in parallel ({timings['retrieve_parallel']:.0f} ms)")
    for store in ("sql", "mongo", "vector"):
        if store not in result.snippets:
            print(f"    {paint(STORE_NAMES[store], '1')}: not needed for this question")
            continue
        items = result.snippets[store]
        print(f"    {paint(STORE_NAMES[store], '1')}: {len(items)} result(s) in {timings[store]:.0f} ms")
        for snippet in items:
            print(f"      {snippet.record_id:<34} {' '.join(snippet.text.split())[:58]}...")
    for store, error in result.errors.items():
        print(paint(f"    ERROR in {store}: {error}", "31"))


def show_context(snippets, prompt, result):
    total = sum(len(items) for items in result.snippets.values())
    header(3, f"CONTEXT: {len(snippets)} of {total} results kept, joined into one {len(prompt):,}-character string")
    for snippet in snippets:
        print(f"    [{snippet.tag:<3}] {snippet.db + '.' + snippet.source:<40} {snippet.record_id}")
    print("    Sent to Gemini: the rules + these tagged snippets + the question. The databases stay on EC2.")


def show_prompt(prompt):
    """Print the exact string passed to Gemini as `contents`, unchanged, between two marker lines."""
    print("\n" + paint(f"    PROMPT SENT TO GEMINI: exact text, {len(prompt):,} characters", "1;33"))
    print(paint("-" * WIDTH, "2"))
    print(prompt)
    print(paint("-" * WIDTH, "2"))


def verify(answer, snippets, plan, llm_error):
    check = extractive_verification(snippets) if llm_error else verify_answer(answer, snippets)
    omitted = []
    if plan.has_exact_entity and plan.wants_history and not llm_error:
        omitted = [s.record_id for s in snippets if s.source == "rag_payloads" and s.record_id not in answer]
    return check, omitted


def show_verification(check, omitted, snippets):
    if check["factual"]:
        header(5, f"VERIFICATION: {check['supported']}/{check['factual']} factual statements traceable to cited evidence")
    else:
        header(5, "VERIFICATION: no factual claims to check, the answer only states what the records do not show")
    for item in check["statements"]:
        if item["verdict"] == "no_claim":
            mark = paint("  -  ", "2")
        elif item["verdict"] == "supported":
            mark = paint(" OK  ", "32")
        else:
            mark = paint("FLAG ", "31")
        print(f"    {mark} {item['statement'][:WIDTH - 12]}")
        for problem in item.get("problems", []):
            print(paint(f"          {problem}", "31"))
    for record in omitted:
        print(paint(f"    FLAG  retrieved but not mentioned: {record}", "31"))
    cited = {tag for item in check["statements"] for tag in item["cites"]}
    if cited:
        print("\n    Cited sources:")
    for snippet in snippets:
        if snippet.tag in cited:
            print(f"      [{snippet.tag}] {source_line(snippet.citation())}")


def show_latency(timings):
    stages = ["route", "resolve", "encode", "retrieve_parallel", "assemble", "generate", "verify"]
    total_s = sum(timings.get(stage, 0) for stage in stages) / 1000
    header(6, "LATENCY: measured pipeline time, without the demo's pauses")
    print("    " + " | ".join(f"{stage} {timings[stage]:.0f} ms" for stage in stages if stage in timings))
    status = paint("under target", "32") if total_s < TARGET_S else paint("OVER target", "31")
    print(f"    Total: {total_s:.2f} s, {status} of {TARGET_S:.0f} s")
    if timings.get("rate_limit_wait"):
        print(paint(f"    Not included: {timings['rate_limit_wait'] / 1000:.0f} s spent waiting to retry Gemini", "33"))


def run_question(pipeline, question, pause, show_full_prompt=True):
    print("\n" + paint("=" * WIDTH, "2") + f"\nQUESTION: {question}")
    result = pipeline.retriever.retrieve(question)
    timings = dict(result.timings_ms)
    show_routing(result)
    pause()
    show_retrieval(result)
    pause()

    start = time.perf_counter()
    snippets = assemble_context(result)
    prompt = build_prompt(snippets, question)
    timings["assemble"] = (time.perf_counter() - start) * 1000
    show_context(snippets, prompt, result)
    if show_full_prompt:
        show_prompt(prompt)
    pause()

    header(4, f"ANSWER from {pipeline.backend.name}")
    answer, llm_error = pipeline._generate(prompt, snippets, timings)
    wrapped(answer)
    if llm_error:
        print(paint(f"    LLM error: {llm_error}", "31"))
    pause()

    start = time.perf_counter()
    check, omitted = verify(answer, snippets, result.plan, llm_error)
    timings["verify"] = (time.perf_counter() - start) * 1000
    show_verification(check, omitted, snippets)
    show_latency(timings)
    return prompt


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-pause", action="store_true")
    ap.add_argument("--hide-prompt", action="store_true", help="do not print the full prompt before each Gemini call")
    args = ap.parse_args()

    def pause():
        if not args.no_pause:
            input(paint("    (Enter to continue)", "2"))

    print("Loading the embedding model and connecting to MariaDB, MongoDB and ChromaDB ...")
    pipeline = RagPipeline()
    pipeline.warmup()
    print(f"Ready. Generator: {pipeline.backend.name} on {os.uname().nodename}")
    start = time.perf_counter()
    try:        # shows Gemini's current speed before you start recording
        pipeline.backend.generate("Reply with the single word OK.")
        print(f"Gemini check: responded in {time.perf_counter() - start:.2f} s")
    except Exception as exc:
        print(paint(f"Gemini check failed: {type(exc).__name__}: {str(exc)[:150]}", "31"))

    last_prompt = None
    while True:
        print("\nPresets:")
        for number, question in enumerate(PRESETS, start=1):
            print(f"  {number}. {question}")
        try:
            choice = input("\nType a question, a preset number, 'p' for the last prompt, or 'q': ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if choice.lower() in ("q", "quit", "exit"):
            break
        if choice.lower() == "p":
            print(last_prompt or "No question has been asked yet.")
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(PRESETS):
            choice = PRESETS[int(choice) - 1]
        if choice:
            try:
                last_prompt = run_question(pipeline, choice, pause, not args.hide_prompt)
            except (EOFError, KeyboardInterrupt):
                break


if __name__ == "__main__":
    main()
