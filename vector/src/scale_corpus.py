"""
scale_corpus.py - grow the benchmark corpus beyond the ~25 manuals.

WHY: 25 one-to-three page manuals produce only ~200 chunks. HNSW on ~200
vectors is effectively exact search, so recall is ~1.0 for any setting and
tuning M / ef shows nothing. To make the benchmark meaningful we enlarge the
corpus to a few thousand vectors using two sources:

  1. synthesize_chunks()      - recombine REAL sentences from the manuals into new
                                chunks (same vocabulary and embedding distribution
                                as the real data). Clearly labelled chunk_type=
                                "synthetic" and doc_id "SYNTH-<type>".
  2. load_incident_reports()  - the 100 REAL incident reports from the class lab script
                                generate_embeddings.py (parsed from its RAW_REPORTS text).
  3. load_service_records()   - OPTIONAL: real ERP service-log text from MariaDB
                                (e.g. Phase 2's full_service_context column).
                                Adapt table/column names to your own schema.

The demo/relevance collection stays real-only; synthetic data is used ONLY for
the latency / recall-vs-exact benchmark. Say so in your video and write-up.
"""

import random
import re
from pathlib import Path
from typing import Dict, List, Optional

from chunker import ChunkConfig, chunk_text, split_sentences


def synthesize_chunks(real_chunks: List[Dict], n_target: int, seed: int = 42,
                      sentences_per_chunk=(3, 6)) -> List[Dict]:
    """Return enough synthetic chunks so that len(real)+len(synthetic) == n_target."""
    rng = random.Random(seed)
    pools: Dict[str, List[str]] = {}
    for c in real_chunks:
        pools.setdefault(c.get("doc_type", "DOC"), []).extend(split_sentences(c["text"]))
    pools = {k: [s for s in v if len(s.split()) >= 4] for k, v in pools.items()}
    pools = {k: v for k, v in pools.items() if v}
    types = sorted(pools)
    if not types:
        raise ValueError("no sentences available to synthesize from")

    out: List[Dict] = []
    n_new = max(0, n_target - len(real_chunks))
    for i in range(n_new):
        t = types[i % len(types)]
        k = rng.randint(*sentences_per_chunk)
        sents = rng.sample(pools[t], min(k, len(pools[t])))
        text = " ".join(sents)
        out.append({
            "id": f"SYNTH-{t}::c{i:05d}", "doc_id": f"SYNTH-{t}", "doc_type": t,
            "source_file": "synthetic", "title": "Synthetic recombination",
            "chunk_index": i, "chunk_type": "synthetic", "section": "", "page": 1,
            "token_count": int(len(text.split()) * 1.3),
            "text": text, "embed_text": text,
        })
    return out


def load_incident_reports(path) -> List[Dict]:
    """Real incident reports from the class lab (100 pipe-delimited lines: "Subsystem|Severity|Summary").

    `path` may be the plain data file data/incident_reports.txt, or the class script
    generate_embeddings.py (its RAW_REPORTS string is parsed; the script is never executed).
    Each report becomes one chunk (chunk_type="incident_report").
    """
    path = Path(path)
    if not path.exists():
        print(f"[scale_corpus] {path} not found - skipping incident reports")
        return []
    raw = path.read_text(encoding="utf-8", errors="replace")
    m = re.search(r'RAW_REPORTS\s*=\s*"""(.*?)"""', raw, re.S)
    body = m.group(1) if m else raw
    lines_in = [l for l in body.strip().splitlines() if l.strip() and not l.lstrip().startswith("#")]
    if not lines_in:
        print("[scale_corpus] no incident lines found - skipping incident reports")
        return []
    sev = {"C": "CRITICAL", "H": "HIGH", "M": "MEDIUM", "L": "LOW"}
    chunks: List[Dict] = []
    for i, line in enumerate(lines_in):
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        subsystem, sv, text = parts[0].strip(), sev.get(parts[1].strip(), parts[1].strip()), parts[2].strip()
        doc_id = f"INC-{i:03d}"
        title = f"{subsystem} incident, {sv}"
        chunks.append({
            "id": f"{doc_id}::c000", "doc_id": doc_id, "doc_type": "TELEMETRY",
            "source_file": path.name, "title": title, "chunk_index": 0,
            "chunk_type": "incident_report", "section": subsystem, "page": 1,
            "token_count": int(len(text.split()) * 1.3),
            "text": text, "embed_text": f"[{doc_id} | {title}] {text}",
        })
    return chunks


def load_service_records(sql: str, cfg: Optional[ChunkConfig] = None, count=None,
                         host: str = "localhost", user: str = "student",
                         password: str = "CHANGE_ME",
                         database: str = "gigavolt_vector_lab") -> List[Dict]:
    """Chunk ERP service-record text pulled from MariaDB.

    `sql` must return two columns: (record_id, text). Example - adapt to your schema:
        SELECT service_log_id, full_service_context FROM Service_Logs
        WHERE full_service_context IS NOT NULL
    """
    import pymysql
    from chunker import make_token_counter

    cfg = cfg or ChunkConfig()
    count = count or make_token_counter(cfg.tokenizer_name)
    conn = pymysql.connect(host=host, user=user, password=password, database=database)
    chunks: List[Dict] = []
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
            for rec_id, text in cur.fetchall():
                if not text or not str(text).strip():
                    continue
                meta = {"doc_id": f"SVC-{rec_id}", "doc_type": "SVC",
                        "title": "Service record", "source_file": "mariadb:Service_Logs"}
                for ch in chunk_text(str(text), meta, cfg, count):
                    ch["chunk_type"] = "service_record"
                    chunks.append(ch)
    finally:
        conn.close()
    return chunks
