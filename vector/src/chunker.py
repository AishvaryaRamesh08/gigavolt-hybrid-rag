"""
chunker.py - Phase 4 chunking engine for Gigavolt technical documents.

Pipeline:  PDF/TXT  ->  clean text + table rows  ->  sentence units
           ->  token-budgeted chunks with sentence-level overlap  ->  chunks.jsonl

Key design choices (see README for the full rationale):
  * Token counts come from the embedding model's own tokenizer, so a chunk
    that "fits" really fits (all-MiniLM-L6-v2 silently truncates at 256 tokens).
  * Chunks are built from whole sentences; overlap is also whole sentences,
    so no chunk starts or ends mid-sentence.
  * Headings are "sticky": a heading never ends a chunk, it travels with the
    text it introduces.
  * Tables are extracted separately (pdfplumber) and each table row becomes
    its own self-describing chunk ("Header: value; Header: value; ...").
  * Every embedded string is prefixed with "[doc_id | title | section]" so a
    chunk like "Torque limit: 14.5 N.m" still says which part it belongs to.

Usage:
    python src/chunker.py --input manuals --output results/chunks.jsonl \
        --max-tokens 128 --overlap 32 --min-tokens 24
"""

import argparse
import json
import re
import statistics
import sys
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

import pdfplumber

from paths import MANUALS, RESULTS


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------
@dataclass
class ChunkConfig:
    max_tokens: int = 128            # token budget for the chunk BODY (prefix excluded)
    overlap_tokens: int = 32         # approx. tokens repeated from the previous chunk
    min_tokens: int = 24             # tiny trailing chunks are merged into the previous one
    max_table_row_tokens: int = 220  # table rows longer than this are hard-split
    context_prefix: bool = True      # prepend "[doc_id | title | section]" for embedding
    table_rows_as_chunks: bool = True
    tokenizer_name: str = "sentence-transformers/all-MiniLM-L6-v2"


# --------------------------------------------------------------------------
# Token counting (real tokenizer when available, estimate otherwise)
# --------------------------------------------------------------------------
def make_token_counter(tokenizer_name: str) -> Callable[[str], int]:
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(tokenizer_name)
        return lambda s: len(tok.encode(s, add_special_tokens=False))
    except Exception as exc:  # offline / not installed
        print(f"[chunker] WARNING: tokenizer unavailable ({exc.__class__.__name__}); "
              f"using word-piece estimate (words x 1.3).", file=sys.stderr)
        return lambda s: int(len(re.findall(r"\w+|[^\w\s]", s)) * 1.3) + 1


# --------------------------------------------------------------------------
# Text cleaning helpers
# --------------------------------------------------------------------------
BULLET_RE = re.compile(r"^\s*(?:[\u2514\u251C\u2502\u250C][\u2500\s]*|[\u25CF\u2022\u25AA\u25E6*\-]\s+)")
NUMBERED_RE = re.compile(r"^\s*\d{1,2}[.)]\s+")
SMALL_WORDS = {"and", "of", "for", "the", "to", "in", "on", "a", "an", "&", "or", "vs", "with", "by"}
# common short words that legitimately start a wrapped line (never a split-word fragment)
COMMON_SHORT = {"a", "an", "as", "at", "be", "by", "do", "if", "in", "is", "it", "no", "of",
                "on", "or", "so", "to", "up", "we", "and", "the", "for", "are", "was", "via",
                "per", "can", "not", "but", "all", "any", "has", "had", "may", "its", "our",
                "out", "off", "set", "one", "two", "use", "new"}
WORD_ENDINGS = {"s", "es", "d", "ed", "er", "ers", "ing", "ings", "ly", "al", "ion", "ions", "ity",
                "ment", "ments", "ies", "ize", "ise", "ance", "ence", "able", "ible"}
CODE_END_RE = re.compile(r"[A-Z0-9]+-[A-Z0-9-]*$")  # line ends with a hyphenated part code


def clean_inline(s: str) -> str:
    """Normalise unicode/LaTeX leftovers and whitespace in a single string."""
    s = re.sub(r"\$([^$]*)\$", lambda m: re.sub(r"[_{}\\]", "", m.group(1)), s)  # $LiFePO_4$ -> LiFePO4
    s = s.replace("\u2212", "-").replace("\u2013", "-").replace("\u2014", "-")
    s = s.replace("\u00a0", " ")
    return re.sub(r"[ \t]+", " ", s).strip()


def smart_join(a: str, b: str) -> str:
    """Join two wrapped fragments, repairing words/part-numbers split by the PDF layout.

    'CEL-NMC-06' + '5'     -> 'CEL-NMC-065'
    'Technologie' + 's'    -> 'Technologies'
    'foo bar' + 'baz'      -> 'foo bar baz'   (normal wrap: keep the space)
    """
    a, b = a.rstrip(), b.lstrip()
    if not a:
        return b
    if not b:
        return a
    if a.endswith("-") and not a.endswith(" -"):
        return a + b                                   # hyphenated line break
    first = re.match(r"[^\s]+", b).group(0)
    if CODE_END_RE.search(a.split()[-1]) and re.match(r"^[A-Za-z0-9)]", first) and not first.islower():
        return a + b                                   # part number split mid-token
    bare = re.sub(r"[^a-z]", "", first)
    stub = re.split(r"[-\s]", a)[-1]
    if a[-1].isalpha() and first[0].islower() and bare and len(first) <= 5:
        ends_word = bare in WORD_ENDINGS                               # 'Technologie'+'s', 'microcontroll'+'ers.'
        after_stub = (bool(re.search(r"\w-[A-Za-z]{1,3}$", a)) and stub.lower() not in COMMON_SHORT
                      and bare not in COMMON_SHORT)                  # 'automotive-gr'+'ade' (hyphen compounds only)
        if ends_word or after_stub:
            return a + b
    return a + " " + b


def join_lines(lines: List[str]) -> str:
    out = ""
    for ln in lines:
        out = smart_join(out, clean_inline(ln))
    return out


def is_heading(line: str) -> bool:
    """Short Title-Case line without terminal punctuation (e.g. 'Dispatch Workflow')."""
    s = line.strip()
    if not s or len(s) > 80 or s[-1] in ".,;":
        return False
    if s[-1] == ")" and s.count("(") != s.count(")"):
        return False
    words = s.split()
    if len(words) > 9 or BULLET_RE.match(s) or NUMBERED_RE.match(s):
        return False
    for w in words:
        core = re.sub(r"^[^A-Za-z0-9]+", "", w)
        if not core:
            continue
        if core.lower() in SMALL_WORDS:
            continue
        if not (core[0].isupper() or core[0].isdigit()):
            return False
    return True


# --------------------------------------------------------------------------
# Document extraction
# --------------------------------------------------------------------------
def doc_meta_from_filename(path: Path) -> Dict:
    """'GV-SPEC-CELL-LFP-08_Datasheet.pdf' or 'GV-SPEC-CELL-LFP-08 Datasheet.pdf' -> doc_id, doc_type, title.

    The document id is everything before the first space or underscore (ids contain only hyphens).
    """
    stem = path.stem
    m = re.match(r"^([^\s_]+)[\s_]+(.*)$", stem)
    doc_id, rest = (m.group(1), m.group(2)) if m else (stem, "")
    parts = doc_id.split("-")
    doc_type = parts[1] if len(parts) > 1 and parts[0] == "GV" else "DOC"
    rest = re.sub(r"_\d$", "", rest)                      # drop browser re-download suffix (e.g. "..._1")
    title = rest.replace("_", " ").strip() or doc_id
    return {"doc_id": doc_id, "doc_type": doc_type, "title": title, "source_file": path.name}


def _in_any_bbox(obj, bboxes) -> bool:
    x = (obj.get("x0", 0) + obj.get("x1", 0)) / 2
    y = (obj.get("top", 0) + obj.get("bottom", 0)) / 2
    return any(b[0] <= x <= b[2] and b[1] <= y <= b[3] for b in bboxes)


def extract_pdf(path: Path) -> Tuple[List[Tuple[int, str]], List[Dict]]:
    """Return (lines_with_page_numbers, table_rows).

    Table regions are removed from the running text and returned as structured
    rows, each carrying ITS OWN table's header. Handling of multi-page tables:
      * a repeated header row at the top of the next page is skipped;
      * a table that starts at the top of a later page with the same column count
        (and no repeated header) is treated as a continuation of the previous table;
      * rows with an empty first cell are merged into the row they continue.
    Anything else starts a new table whose first row is its header.
    """
    lines: List[Tuple[int, str]] = []
    rows: List[Dict] = []
    header: Optional[List[str]] = None
    last_table_page = 0
    with pdfplumber.open(str(path)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            bboxes = [t.bbox for t in tables]
            body = page.filter(lambda o: not _in_any_bbox(o, bboxes)) if bboxes else page
            for ln in (body.extract_text() or "").splitlines():
                if ln.strip():
                    lines.append((pno, ln))
            for t in tables:
                raw_rows = [[join_lines((c or "").split("\n")) for c in r] for r in t.extract()]
                if not raw_rows:
                    continue
                first = raw_rows[0]
                at_top = t.bbox[1] < page.height * 0.2
                continuation = (header is not None and len(first) == len(header)
                                and (first == header or (at_top and pno > last_table_page)))
                if continuation:
                    data = raw_rows[1:] if first == header else raw_rows
                else:
                    header, data = first, raw_rows[1:]
                last_table_page = pno
                for cells in data:
                    if not any(cells):
                        continue
                    if not cells[0] and rows and rows[-1]["header"] is header:   # continuation of previous row
                        prev = rows[-1]["cells"]
                        for i, c in enumerate(cells):
                            if c:
                                prev[i] = smart_join(prev[i], c)
                        continue
                    rows.append({"page": pno, "header": header, "cells": cells})
    return lines, rows


def extract_txt(path: Path) -> Tuple[List[Tuple[int, str]], List[Dict]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    return [(1, ln) for ln in text.splitlines() if ln.strip()], []


def table_row_to_text(header: List[str], cells: List[str]) -> str:
    parts = [f"{h}: {c}" for h, c in zip(header, cells) if c]
    text = "; ".join(parts)
    return text if text.endswith(".") else text + "."


# --------------------------------------------------------------------------
# Sentence units
# --------------------------------------------------------------------------
@dataclass
class Unit:
    text: str
    tokens: int
    heading: bool = False
    section: str = ""
    page: int = 1
    newline_before: bool = False   # headings / bullets / numbered steps start a new line


ABBREV = ["e.g.", "i.e.", "etc.", "vs.", "approx.", "Fig.", "No.", "Inc.", "Ltd.", "Corp.", "Co.", "Dr.", "Eq."]
SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"])")


def split_sentences(text: str) -> List[str]:
    protected = re.sub(r"^(\d{1,2})\.(\s)", r"\1<NUMDOT>\2", text)   # '2. Parts...' is a list marker
    for i, ab in enumerate(ABBREV):
        protected = protected.replace(ab, ab.replace(".", f"<DOT{i}>"))
    parts = SENT_SPLIT_RE.split(protected)
    out = []
    for p in parts:
        for i, ab in enumerate(ABBREV):
            p = p.replace(ab.replace(".", f"<DOT{i}>"), ab)
        p = p.replace("<NUMDOT>", ".").strip()
        if p:
            out.append(p)
    return out


def hard_split(text: str, limit: int, count: Callable[[str], int]) -> List[str]:
    """Last resort for a single 'sentence' larger than the budget: split on words."""
    words, pieces, cur = text.split(), [], []
    for w in words:
        if cur and count(" ".join(cur + [w])) > limit:
            pieces.append(" ".join(cur))
            cur = []
        cur.append(w)
    if cur:
        pieces.append(" ".join(cur))
    return pieces


def build_units(lines: List[Tuple[int, str]], cfg: ChunkConfig, count: Callable[[str], int]) -> List[Unit]:
    units: List[Unit] = []
    buf: List[str] = []
    buf_page = 1
    buf_nl = False
    section = ""

    def flush():
        nonlocal buf, buf_nl
        if not buf:
            return
        text = join_lines(buf)
        first = True
        for sent in split_sentences(text):
            nl = buf_nl and first
            first = False
            if count(sent) > cfg.max_tokens:
                for j, piece in enumerate(hard_split(sent, cfg.max_tokens, count)):
                    units.append(Unit(piece, count(piece), False, section, buf_page, nl and j == 0))
            else:
                units.append(Unit(sent, count(sent), False, section, buf_page, nl))
        buf, buf_nl = [], False

    for page, raw in lines:
        line = clean_inline(raw)
        if not line:
            continue
        if BULLET_RE.match(line):
            flush()
            buf, buf_page, buf_nl = [BULLET_RE.sub("", line)], page, True
        elif NUMBERED_RE.match(line):
            flush()
            buf, buf_page, buf_nl = [line], page, True
        elif is_heading(line) and (not buf or buf[-1].rstrip()[-1:] in ".!?:)"):
            flush()
            section = line
            units.append(Unit(line, count(line), True, section, page, True))
        else:
            if not buf:
                buf_page = page
            buf.append(line)
    flush()
    return units


# --------------------------------------------------------------------------
# Chunk packing with sentence-level overlap
# --------------------------------------------------------------------------
def overlap_tail(units: List[Unit], overlap_tokens: int) -> List[Unit]:
    """Trailing whole sentences (never headings) totalling >= overlap_tokens."""
    tail, total = [], 0
    for u in reversed(units):
        if u.heading:
            continue
        tail.insert(0, u)
        total += u.tokens
        if total >= overlap_tokens:
            break
    return tail


def pack_units(units: List[Unit], cfg: ChunkConfig) -> List[Dict]:
    chunks: List[Dict] = []
    cur: List[Unit] = []
    cur_tok = 0
    n_overlap = 0        # how many leading units of `cur` are repeated overlap

    def emit():
        nonlocal cur, cur_tok, n_overlap
        # sticky headings: a trailing heading moves to the next chunk (only if the chunk has body text;
        # a pure run of headings/metadata lines is emitted as its own chunk)
        carry = []
        if any(not u.heading for u in cur):
            while cur and cur[-1].heading:
                carry.insert(0, cur.pop())
        body = cur[n_overlap:] if len(cur) > n_overlap else cur
        if cur:
            chunks.append({"units": list(cur), "new_tokens": sum(u.tokens for u in body)})
        tail = overlap_tail(cur, cfg.overlap_tokens)
        cur = tail + carry
        cur_tok = sum(u.tokens for u in cur)
        n_overlap = len(tail)

    for u in units:
        while (cur and cur_tok + u.tokens > cfg.max_tokens
               and (any(not x.heading for x in cur[n_overlap:] or cur) or cur_tok > cfg.max_tokens * 0.35)):
            emit()
            # guard: overlap + next unit must fit the budget
            while cur and cur_tok + u.tokens > cfg.max_tokens and n_overlap > 0:
                dropped = cur.pop(0)
                cur_tok -= dropped.tokens
                n_overlap -= 1
        cur.append(u)
        cur_tok += u.tokens
    if cur and any(not x.heading for x in cur[n_overlap:]):
        chunks.append({"units": list(cur), "new_tokens": sum(x.tokens for x in cur[n_overlap:])})

    # merge a tiny trailing chunk (its content is mostly overlap) into the previous one
    if len(chunks) > 1 and chunks[-1]["new_tokens"] < cfg.min_tokens:
        last = chunks.pop()
        new_units = last["units"][-max(1, len(last["units"]) - _overlap_len(chunks[-1], last)):]
        merged = chunks[-1]["units"] + new_units
        if sum(x.tokens for x in merged) <= int(cfg.max_tokens * 1.25):
            chunks[-1]["units"] = merged
        else:
            chunks.append(last)
    return chunks


def _overlap_len(prev: Dict, nxt: Dict) -> int:
    prev_ids = {id(u) for u in prev["units"]}
    return sum(1 for u in nxt["units"] if id(u) in prev_ids)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def render_units(us: List[Unit]) -> str:
    out = ""
    for u in us:
        out += ("\n" if u.newline_before and out else (" " if out else "")) + u.text
    return out


def make_prefix(meta: Dict, section: str) -> str:
    sec = f" | {section}" if section else ""
    return f"[{meta['doc_id']} | {meta['title']}{sec}] "


def chunk_file(path: Path, cfg: ChunkConfig, count: Callable[[str], int]) -> List[Dict]:
    meta = doc_meta_from_filename(path)
    suffix = path.suffix.lower()
    lines, table_rows = extract_pdf(path) if suffix == ".pdf" else extract_txt(path)
    return _chunks_from(lines, table_rows, meta, cfg, count)


def chunk_text(text: str, meta: Dict, cfg: ChunkConfig, count: Callable[[str], int]) -> List[Dict]:
    """Chunk an in-memory string (e.g. an ERP service record). meta needs doc_id/doc_type/title/source_file."""
    lines = [(1, ln) for ln in text.splitlines() if ln.strip()]
    return _chunks_from(lines, [], meta, cfg, count)


def _chunks_from(lines, table_rows, meta: Dict, cfg: ChunkConfig, count: Callable[[str], int]) -> List[Dict]:
    out: List[Dict] = []

    def add(text: str, ctype: str, section: str, page: int, n_tok: int):
        idx = len(out)
        prefix = make_prefix(meta, section) if cfg.context_prefix else ""
        out.append({
            "id": f"{meta['doc_id']}::c{idx:03d}",
            "doc_id": meta["doc_id"], "doc_type": meta["doc_type"],
            "source_file": meta["source_file"], "title": meta["title"],
            "chunk_index": idx, "chunk_type": ctype, "section": section,
            "page": page, "token_count": n_tok,
            "text": text, "embed_text": prefix + text,
        })

    units = build_units(lines, cfg, count)
    for ch in pack_units(units, cfg):
        us = ch["units"]
        text = render_units(us)
        first_body = next((u for u in us if not u.heading), us[0])
        add(text, "text", first_body.section, first_body.page, sum(u.tokens for u in us))

    if cfg.table_rows_as_chunks:
        for row in table_rows:
            text = table_row_to_text(row["header"], row["cells"])
            pieces = [text]
            if count(text) > cfg.max_table_row_tokens:
                pieces = hard_split(text, cfg.max_table_row_tokens, count)
            for p in pieces:
                add(p, "table_row", "Table", row["page"], count(p))
    return out


def find_documents(root: Path) -> List[Path]:
    exts = {".pdf", ".txt"}
    return sorted(p for p in root.rglob("*") if p.suffix.lower() in exts and p.is_file())


def chunk_corpus(root: Path, cfg: ChunkConfig) -> List[Dict]:
    count = make_token_counter(cfg.tokenizer_name)
    all_chunks: List[Dict] = []
    for path in find_documents(root):
        try:
            chunks = chunk_file(path, cfg, count)
        except Exception as exc:
            print(f"[chunker] ERROR on {path.name}: {exc}", file=sys.stderr)
            continue
        if not chunks:
            print(f"  {path.name:<75}   0 chunks  <-- WARNING: no text extracted (scanned PDF? needs OCR)")
            continue
        print(f"  {path.name:<75} {len(chunks):>3} chunks")
        all_chunks.extend(chunks)

    # Chroma requires unique ids; two files sharing a doc_id (e.g. X.pdf and X.txt) would collide
    seen: Dict[str, int] = {}
    for c in all_chunks:
        n = seen.get(c["id"], 0)
        seen[c["id"]] = n + 1
        if n:
            c["id"] = f"{c['id']}#dup{n}"
    return all_chunks


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", default=str(MANUALS))
    ap.add_argument("--output", default=str(RESULTS / "chunks.jsonl"))
    d = ChunkConfig()
    ap.add_argument("--max-tokens", type=int, default=d.max_tokens)
    ap.add_argument("--overlap", type=int, default=d.overlap_tokens)
    ap.add_argument("--min-tokens", type=int, default=d.min_tokens)
    ap.add_argument("--no-prefix", action="store_true", help="do not prepend [doc | title | section]")
    ap.add_argument("--no-table-chunks", action="store_true")
    args = ap.parse_args()

    cfg = ChunkConfig(max_tokens=args.max_tokens, overlap_tokens=args.overlap, min_tokens=args.min_tokens,
                      context_prefix=not args.no_prefix, table_rows_as_chunks=not args.no_table_chunks)
    print(f"Chunk config: {asdict(cfg)}\n")
    chunks = chunk_corpus(Path(args.input), cfg)
    if not chunks:
        sys.exit("No chunks produced - check --input path.")

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as fh:
        for c in chunks:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")

    toks = [c["token_count"] for c in chunks]
    print(f"\nWrote {len(chunks)} chunks -> {out}")
    print(f"tokens/chunk  min={min(toks)}  median={int(statistics.median(toks))}  max={max(toks)}  "
          f"docs={len({c['doc_id'] for c in chunks})}")


if __name__ == "__main__":
    main()
