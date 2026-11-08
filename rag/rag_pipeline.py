#!/usr/bin/env python3
"""
rag_pipeline.py - End-to-end RAG: question -> hybrid retrieval -> LLM -> verified, cited answer.

Generator : Gemini by default (LLM_BACKEND=gemini), or a local model (LLM_BACKEND=ollama).
            If the LLM is unavailable, an extractive answer of the top evidence is returned and
            labelled as such, so a question never fails silently.
Provenance: every snippet carries database, record ID, document, chunk and timestamp.
            verify_answer() then checks the answer against the cited evidence:
              - every factual statement must cite a tag that exists
              - numbers and IDs in a statement must appear in the evidence it cites
Latency   : every stage is timed. The embedding model stays loaded between questions.

Usage:
    python rag_pipeline.py                    # interactive question loop (use this for the demo)
    python rag_pipeline.py --q "question"     # one question
"""
import argparse
import json
import os
import re
import time
from pathlib import Path

from hybrid_retrieval import HybridRetriever, assemble_context, format_snippet

TEMPLATE_PATH = Path(__file__).with_name("prompt_template.txt")
RUN_LOG = Path(os.environ.get("RAG_RUN_LOG", "/opt/gigavolt/logs/rag_runs.jsonl"))
MAX_OUTPUT_TOKENS = 900    # 500 cut off the longest history and spec answers

CITATION_RE = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_.-])\d[\d,]*(?:\.\d+)?(?![A-Za-z0-9_-])")
EVIDENCE_NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
ID_RE = re.compile(r"\b(?:EQ|DISP|CLM|PRT|TLM|SN|GV|ERR)[-_][A-Za-z0-9_-]*[A-Za-z0-9]\b")
ABSTAIN_RE = re.compile(r"\b(do not|does not|don't|doesn't|no|not|cannot|could not|unable)\b.*"
                        r"\b(show|record|records|information|evidence|data|available|found|exist|exists|contain|mention)\b",
                        re.IGNORECASE)
SENTENCE_RE = re.compile(r"(?<=[.!?\]])\s+(?=[A-Z])")


def build_prompt(snippets, question):
    context = "\n\n".join(format_snippet(snippet) for snippet in snippets) or "(no evidence was retrieved)"
    return TEMPLATE_PATH.read_text(encoding="utf-8").replace("{context}", context).replace("{question}", question)


def extract_tags(statement):
    tags = []
    for group in CITATION_RE.findall(statement):
        tags += re.split(r"\s*[,;]\s*", group)
    return tags


def split_statements(answer):
    statements = []
    for line in answer.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s+", "", line).replace("**", "").strip()
        if line and not line.startswith("#"):
            statements += [part.strip() for part in SENTENCE_RE.split(line) if re.search(r"[A-Za-z]", part)]
    return statements


def to_number(text):
    return float(text.replace(",", ""))


def verify_answer(answer, snippets):
    """Checks each statement against the evidence it cites. A failed check is reported, never hidden."""
    by_tag = {snippet.tag: snippet for snippet in snippets}
    checked = []
    for statement in split_statements(answer):
        tags = extract_tags(statement)
        body = CITATION_RE.sub("", statement).strip()
        states_gap = body.lower().startswith(("the available records do not", "the records do not"))
        if states_gap or (not tags and (body.endswith(":") or ABSTAIN_RE.search(body))):
            checked.append({"statement": statement, "verdict": "no_claim", "cites": []})
            continue
        problems = []
        if not tags:
            problems.append("no citation")
        unknown = [tag for tag in tags if tag not in by_tag]
        if unknown:
            problems.append(f"unknown citation {', '.join(unknown)}")
        cited = [by_tag[tag] for tag in tags if tag in by_tag]
        if cited:
            evidence = " ".join(f"{s.record_id} {s.doc} {s.text}" for s in cited)
            known_numbers = {to_number(n) for n in EVIDENCE_NUMBER_RE.findall(evidence) if n.strip(",")}
            for number in NUMBER_RE.findall(body):
                if number.strip(",") and to_number(number) not in known_numbers:
                    problems.append(f"number {number} not in cited evidence")
            for identifier in ID_RE.findall(body):
                if identifier not in evidence:
                    problems.append(f"ID {identifier} not in cited evidence")
            for date in DATE_RE.findall(body):
                if date not in evidence:
                    problems.append(f"date {date} not in cited evidence")
        checked.append({"statement": statement, "verdict": "problem" if problems else "supported",
                        "cites": tags, "problems": problems})
    factual = [item for item in checked if item["verdict"] != "no_claim"]
    supported = sum(1 for item in factual if item["verdict"] == "supported")
    return {"statements": checked, "factual": len(factual), "supported": supported,
            "traceability_pct": round(100 * supported / len(factual), 1) if factual else None}


def retry_delay(exc):
    """Seconds to wait before one retry, or None if a retry would not help."""
    text = str(exc)
    if "429" in text or "RESOURCE_EXHAUSTED" in text:
        return 20       # free-tier rate limit
    if "503" in text or "UNAVAILABLE" in text:
        return 2        # Gemini is briefly overloaded
    return None


class GeminiBackend:
    def __init__(self):
        from google import genai
        from google.genai import types
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is empty in /opt/gigavolt/config.env")
        self.types = types
        self.client = genai.Client(api_key=key)
        self.model = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
        self.name = f"gemini:{self.model}"

    def generate(self, prompt):
        options = dict(temperature=0.1, max_output_tokens=MAX_OUTPUT_TOKENS)
        # Thinking adds seconds of latency. The setting differs by model generation.
        thinking = self.types.ThinkingConfig(thinking_budget=0) if "2.5" in self.model \
            else self.types.ThinkingConfig(thinking_level="minimal")
        try:
            response = self.client.models.generate_content(
                model=self.model, contents=prompt,
                config=self.types.GenerateContentConfig(thinking_config=thinking, **options))
        except Exception as exc:
            if "thinking" not in str(exc).lower():
                raise
            response = self.client.models.generate_content(   # model rejects the setting: use its default
                model=self.model, contents=prompt, config=self.types.GenerateContentConfig(**options))
        if not response.text:
            raise RuntimeError("Gemini returned an empty response")
        return response.text.strip()


class OllamaBackend:
    def __init__(self):
        self.url = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
        self.model = os.environ.get("LLM_MODEL", "qwen2.5:1.5b")
        self.name = f"ollama:{self.model}"

    def generate(self, prompt):
        import requests
        response = requests.post(f"{self.url}/api/generate", timeout=120, json={
            "model": self.model, "prompt": prompt, "stream": False,
            "options": {"temperature": 0.1, "num_predict": MAX_OUTPUT_TOKENS}})
        response.raise_for_status()
        return response.json()["response"].strip()


def make_backend():
    return OllamaBackend() if os.environ.get("LLM_BACKEND", "gemini") == "ollama" else GeminiBackend()


def extractive_answer(snippets, reason):
    lines = [f"LLM unavailable ({reason}), top retrieved evidence without synthesis:"]
    lines += [f"- {' '.join(snippet.text.split())[:220]} [{snippet.tag}]" for snippet in snippets[:5]]
    return "\n".join(lines)


def extractive_verification(snippets):
    """Extractive lines are copied from the evidence, so each one is traceable to its tag by construction."""
    statements = [{"statement": snippet.text[:120], "verdict": "supported", "cites": [snippet.tag], "problems": []}
                  for snippet in snippets[:5]]
    return {"statements": statements, "factual": len(statements), "supported": len(statements),
            "traceability_pct": 100.0 if statements else None}


class RagPipeline:
    def __init__(self):
        self.retriever = HybridRetriever()
        self.backend = make_backend()

    def warmup(self):
        self.retriever.warmup()

    def _generate(self, prompt, snippets, timings):
        """One retry on a rate limit or overload. Waiting is reported separately from model time."""
        waited = 0.0
        for attempt in (1, 2):
            start = time.perf_counter()
            try:
                answer = self.backend.generate(prompt)
                timings["generate"] = (time.perf_counter() - start) * 1000
                timings["rate_limit_wait"] = waited * 1000
                return answer, None
            except Exception as exc:
                error = f"{type(exc).__name__}: {str(exc)[:200]}"
                delay = retry_delay(exc)
                if attempt == 1 and delay:
                    time.sleep(delay)
                    waited = float(delay)
                    continue
                timings["generate"] = (time.perf_counter() - start) * 1000
                timings["rate_limit_wait"] = waited * 1000
                return extractive_answer(snippets, type(exc).__name__), error

    def ask(self, question):
        started = time.perf_counter()
        result = self.retriever.retrieve(question)
        timings = dict(result.timings_ms)

        start = time.perf_counter()
        snippets = assemble_context(result)
        prompt = build_prompt(snippets, question)
        timings["assemble"] = (time.perf_counter() - start) * 1000

        answer, llm_error = self._generate(prompt, snippets, timings)

        start = time.perf_counter()
        verification = extractive_verification(snippets) if llm_error else verify_answer(answer, snippets)
        timings["verify"] = (time.perf_counter() - start) * 1000
        timings["total"] = (time.perf_counter() - started) * 1000

        # A traceable answer can still leave records out, so report any the question asked for
        verification["omitted_records"] = []
        if result.plan.has_exact_entity and result.plan.wants_history and not llm_error:
            verification["omitted_records"] = [s.record_id for s in snippets if s.source == "rag_payloads"
                                               and s.record_id not in answer]

        cited = {tag for item in verification["statements"] for tag in item["cites"]}
        record = {
            "question": question, "answer": answer, "backend": self.backend.name, "llm_error": llm_error,
            "store_errors": result.errors, "routing": result.plan.reasons, "timings_ms": timings,
            "sources": [{**snippet.citation(), "cited": snippet.tag in cited} for snippet in snippets],
            "verification": verification,
        }
        try:
            RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
            with RUN_LOG.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, default=str) + "\n")
        except OSError as exc:
            print(f"WARNING: could not write {RUN_LOG}: {exc}")
        return record


def source_line(source):
    where = f"{source['db']}.{source['source']} | {source['record_id']}"
    if source.get("doc"):
        where += f" | {source['doc']} p.{source.get('page')}"
    if source.get("timestamp"):
        where += f" | {source['timestamp']}"
    return where


def print_record(record):
    print(f"\nANSWER ({record['backend']})\n{record['answer']}")
    print("\nSOURCES CITED")
    for source in record["sources"]:
        if source["cited"]:
            print(f"  [{source['tag']}] {source_line(source)}")
    check = record["verification"]
    print(f"\nPROVENANCE CHECK: {check['supported']}/{check['factual']} factual statements traceable "
          f"({check['traceability_pct']}%)")
    for item in check["statements"]:
        if item["verdict"] == "problem":
            print(f"  ! {'; '.join(item['problems'])}: {item['statement'][:120]}")
    if check.get("omitted_records"):
        print(f"  ! retrieved but not mentioned: {', '.join(check['omitted_records'])}")
    timings = record["timings_ms"]
    print(f"\nLATENCY: total {timings['total'] / 1000:.2f} s | retrieval {timings['retrieve_parallel']:.0f} ms "
          f"(sql {timings.get('sql', 0):.0f}, vector {timings.get('vector', 0):.0f}, mongo {timings.get('mongo', 0):.0f}) | "
          f"encode {timings['encode']:.0f} ms | generate {timings['generate']:.0f} ms")
    print("ROUTING: " + "; ".join(record["routing"]))
    if record["llm_error"]:
        print(f"LLM ERROR: {record['llm_error']}")
    for store, error in record["store_errors"].items():
        print(f"STORE ERROR ({store}): {error}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--q", help="ask one question and exit")
    args = ap.parse_args()
    print("Loading the embedding model and connecting to the stores ...")
    pipeline = RagPipeline()
    pipeline.warmup()
    print(f"Ready. Generator: {pipeline.backend.name}")
    if args.q:
        print_record(pipeline.ask(args.q))
        return
    while True:
        try:
            question = input("\nQuestion (or 'quit'): ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in ("quit", "exit", "q"):
            break
        if question:
            print_record(pipeline.ask(question))


if __name__ == "__main__":
    main()
