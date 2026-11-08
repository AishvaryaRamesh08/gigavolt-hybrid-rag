#!/usr/bin/env python3
"""
build_vectors.py - Step 5b: build the ChromaDB vector store on EC2.

Creates two collections in CHROMA_PATH, both HNSW + cosine + all-MiniLM-L6-v2 (384-d):
    gv_manuals  chunks of the PDF manuals, reusing the Phase 4 chunker, embedder and schema
    gv_erp      rag_payloads rows produced by sp_Prepare_RAG_Payloads()

all-MiniLM-L6-v2 silently truncates input at 256 tokens. Dispatches with many warranty
claims exceed that, so long payloads are split on line boundaries. Every part repeats the
event and equipment lines, so a claim is never separated from the unit it belongs to.
The script fails if anything would still be truncated.

Run from /opt/gigavolt/src (next to the Phase 4 modules), with config.env loaded:
    python build_vectors.py                # build both collections
    python build_vectors.py --only erp     # rebuild one collection
    python build_vectors.py --batch-size 8 # lower this if the process gets Killed
"""
import argparse
import json
import os
import statistics
import sys
import time
from datetime import datetime, timezone

EVENT_CONTEXT_LINES = 2     # "Service Event ..." and "Equipment ..." repeat in every part
QUERIES = {
    "gv_manuals": "What causes thermal runaway and how should a technician respond?",
    "gv_erp": "emergency dispatch for over-temperature alarm on an X-7000 unit",
}


def split_payload(text, count_tokens, limit):
    """Split a payload into parts of at most `limit` tokens, breaking only between lines."""
    if count_tokens(text) <= limit:
        return [text]
    lines = text.split("\n")
    base = [line for line in lines if not line.startswith("Warranty Claim")]
    claims = [line for line in lines if line.startswith("Warranty Claim")]
    context = "\n".join(lines[:EVENT_CONTEXT_LINES])

    parts, current = [], "\n".join(base)
    for claim in claims:
        candidate = f"{current}\n{claim}"
        if count_tokens(candidate) <= limit:
            current = candidate
        else:
            parts.append(current)
            current = f"{context}\n{claim}"
    parts.append(current)
    return parts


def payload_metadata(raw, payload_id, part_index, part_count, token_count, ingested_at):
    """Chroma metadata values must be scalars: drop nulls and join lists into strings."""
    meta = json.loads(raw) if isinstance(raw, (str, bytes)) else dict(raw or {})
    flat = {}
    for key, value in meta.items():
        if value is None:
            continue
        flat[key] = ",".join(map(str, value)) if isinstance(value, list) else value
    flat.update(payload_id=int(payload_id), part_index=part_index, part_count=part_count,
                token_count=token_count, ingested_at_iso=ingested_at)
    return flat


def payload_items(rows, count_tokens, limit, ingested_at):
    """Turn rag_payloads rows into (id, text, metadata) items for Chroma."""
    items = []
    for row in rows:
        parts = split_payload(row["payload_text"], count_tokens, limit)
        for index, part in enumerate(parts, start=1):
            items.append({
                "id": f"{row['source_table']}:{row['source_id']}::p{index}",
                "text": part,
                "metadata": payload_metadata(row["metadata"], row["payload_id"], index, len(parts),
                                             count_tokens(part), ingested_at),
            })
    return items


def fetch_payloads():
    import pymysql

    conn = pymysql.connect(host=os.environ.get("MARIADB_HOST", "127.0.0.1"),
                           port=int(os.environ.get("MARIADB_PORT", 3306)),
                           user=os.environ["MARIADB_USER"], password=os.environ["MARIADB_PASSWORD"],
                           database=os.environ.get("MARIADB_DB", "gigavolt_erp"),
                           charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT payload_id, source_table, source_id, payload_text, metadata "
                        "FROM rag_payloads ORDER BY payload_id")
            return cur.fetchall()
    finally:
        conn.close()


def check_collection(col, model, expected):
    """Confirm the stored count, then time a real query to prove the collection is searchable."""
    from vectordb import search

    stored = col.count()
    if stored != expected:
        sys.exit(f"{col.name}: stored {stored} but expected {expected}")
    vector = model.encode(QUERIES[col.name], normalize_embeddings=True)
    timings = []
    for _ in range(25):
        start = time.perf_counter()
        result = search(col, vector, k=3)
        timings.append((time.perf_counter() - start) * 1000)
    print(f"  stored {stored}; median search {statistics.median(timings):.1f} ms")
    print(f"  query: {QUERIES[col.name]}")
    for doc_id, distance in zip(result["ids"][0], result["distances"][0]):
        print(f"    {distance:.3f}  {doc_id}")


def build_manuals(client, model, args):
    from chunker import ChunkConfig, chunk_corpus, find_documents
    from embed import count_truncated, embed_texts
    from paths import MANUALS
    from vectordb import add_chunks, create_collection

    documents = find_documents(MANUALS)
    print(f"\n=== gv_manuals: {len(documents)} documents in {MANUALS} ===")
    chunks = chunk_corpus(MANUALS, ChunkConfig())
    covered = {c["source_file"] for c in chunks}
    if len(covered) != len(documents):
        sys.exit(f"Only {len(covered)} of {len(documents)} documents produced chunks; see messages above.")
    texts = [c["embed_text"] for c in chunks]
    truncated = count_truncated(texts, model)
    if truncated:
        sys.exit(f"{truncated} manual chunks exceed the model limit.")
    vectors = embed_texts(texts, model, batch_size=args.batch_size)
    col = create_collection(client, "gv_manuals", args.M, args.ef_construction, args.ef_search)
    add_chunks(col, chunks, vectors)
    check_collection(col, model, len(chunks))


def build_erp(client, model, args):
    import numpy as np

    from embed import count_truncated, embed_texts
    from vectordb import create_collection

    rows = fetch_payloads()
    print(f"\n=== gv_erp: {len(rows)} rag_payloads rows ===")
    if not rows:
        sys.exit("rag_payloads is empty: run CALL sp_Prepare_RAG_Payloads(FALSE) first.")

    def count_tokens(text):
        return len(model.tokenizer.encode(text, add_special_tokens=True))

    ingested_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    items = payload_items(rows, count_tokens, model.max_seq_length, ingested_at)
    texts = [item["text"] for item in items]
    print(f"  {len(items)} items; {len(items) - len(rows)} extra parts from splitting long payloads")
    truncated = count_truncated(texts, model)
    if truncated:
        sys.exit(f"{truncated} ERP items still exceed the model limit.")

    vectors = embed_texts(texts, model, batch_size=args.batch_size)
    col = create_collection(client, "gv_erp", args.M, args.ef_construction, args.ef_search)
    for start in range(0, len(items), 1000):
        batch = items[start:start + 1000]
        col.add(ids=[item["id"] for item in batch],
                documents=[item["text"] for item in batch],
                metadatas=[item["metadata"] for item in batch],
                embeddings=vectors[start:start + 1000].astype(np.float32).tolist())
    check_collection(col, model, len(items))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["all", "manuals", "erp"], default="all")
    ap.add_argument("--batch-size", type=int, default=16, help="lower it if the process gets Killed")
    ap.add_argument("--db", default=os.environ.get("CHROMA_PATH", "/opt/gigavolt/chroma_db"))
    # Defaults are the configuration chosen by the Phase 4 benchmark (recall@5 = 0.952)
    ap.add_argument("--M", type=int, default=16)
    ap.add_argument("--ef-construction", type=int, default=50)
    ap.add_argument("--ef-search", type=int, default=25)
    args = ap.parse_args()

    import chromadb

    from embed import load_model

    start = time.perf_counter()
    model = load_model()
    print(f"Model max_seq_length = {model.max_seq_length} tokens")
    client = chromadb.PersistentClient(path=args.db)
    if args.only in ("all", "manuals"):
        build_manuals(client, model, args)
    if args.only in ("all", "erp"):
        build_erp(client, model, args)
    print(f"\nDone in {time.perf_counter() - start:.0f} s. Chroma path: {args.db}")


if __name__ == "__main__":
    main()
