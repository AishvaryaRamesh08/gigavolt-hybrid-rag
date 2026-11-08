"""
vectordb.py - Phase 4 vector database layer (ChromaDB + HNSW).

Collection definition ("schema")
--------------------------------
  id         "<doc_id>::c<NNN>"                      (unique per chunk)
  embedding  384-d float32, L2-normalised (all-MiniLM-L6-v2)
  document   chunk body text
  metadata   doc_id, doc_type (SPEC/SOP/SUP), source_file, title,
             chunk_index, chunk_type (text|table_row), section, page,
             token_count, ingested_at (epoch seconds), ingested_at_iso
  index      HNSW, cosine distance; M / ef_construction / ef_search configurable

Chroma changed its index-configuration API between releases:
  * 1.x:  create_collection(configuration={"hnsw": {...}})
  * 0.x:  create_collection(metadata={"hnsw:M": ..., ...})
create_collection() tries the new form first and falls back to the old one.
Note: M, ef_construction and ef_search are all set when the collection is created. Changing
ef_search afterwards with set_ef_search() was observed NOT to affect an already-loaded index
(Chroma 1.5.x: identical recall for every ef_search value), so the benchmark builds a separate
collection for every ef_search value instead.

CLI
---
    python src/vectordb.py build
    python src/vectordb.py query                      # interactive demo with latency printout
    python src/vectordb.py query --q "pyrofuse trigger current" --doc-type SPEC
"""

import argparse
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

import chromadb

from paths import RESULTS

DB_PATH = str(RESULTS / "vectordb")
COLLECTION = "gigavolt_docs"
DEFAULTS = dict(M=16, ef_construction=200, ef_search=50, space="cosine")

COLLECTION_API = "unknown"   # set to "configuration" or "metadata" after first create


# --------------------------------------------------------------------------
# Collection management
# --------------------------------------------------------------------------
def create_collection(client, name: str, M: int = DEFAULTS["M"],
                      ef_construction: int = DEFAULTS["ef_construction"],
                      ef_search: int = DEFAULTS["ef_search"], space: str = DEFAULTS["space"]):
    """(Re)create a collection with explicit HNSW parameters."""
    global COLLECTION_API
    try:
        client.delete_collection(name)
    except Exception:
        pass

    try:  # Chroma 1.x style
        col = client.create_collection(
            name=name, embedding_function=None,
            configuration={"hnsw": {"space": space, "ef_construction": ef_construction,
                                    "ef_search": ef_search, "max_neighbors": M}})
        COLLECTION_API = "configuration"
        return col
    except Exception:
        pass

    try:
        client.delete_collection(name)
    except Exception:
        pass
    col = client.create_collection(  # Chroma 0.x style
        name=name, embedding_function=None,
        metadata={"hnsw:space": space, "hnsw:M": M,
                  "hnsw:construction_ef": ef_construction, "hnsw:search_ef": ef_search})
    COLLECTION_API = "metadata"
    return col


def set_ef_search(col, ef_search: int) -> bool:
    """Update the stored ef_search setting. NOT reliable for benchmarking: the already-loaded index may
    keep using the value it was created with. Build a new collection per ef_search value instead."""
    try:
        col.modify(configuration={"hnsw": {"ef_search": ef_search}})
        return True
    except Exception:
        return False


def dir_size_mb(path: str) -> float:
    total = 0
    for root, _, files in os.walk(path):
        for f in files:
            total += os.path.getsize(os.path.join(root, f))
    return total / (1024 * 1024)


# --------------------------------------------------------------------------
# Ingestion
# --------------------------------------------------------------------------
def chunk_metadata(c: Dict, now_epoch: int, now_iso: str) -> Dict:
    """Chroma metadata values must be str/int/float/bool (no None, no lists)."""
    return {
        "doc_id": c["doc_id"], "doc_type": c.get("doc_type", "DOC"),
        "source_file": c.get("source_file", ""), "title": c.get("title", ""),
        "chunk_index": int(c.get("chunk_index", 0)), "chunk_type": c.get("chunk_type", "text"),
        "section": c.get("section", "") or "", "page": int(c.get("page", 1)),
        "token_count": int(c.get("token_count", 0)),
        "ingested_at": now_epoch, "ingested_at_iso": now_iso,
    }


def add_chunks(col, chunks: List[Dict], embeddings: np.ndarray, batch_size: int = 1000) -> float:
    """Ingest chunks + embeddings in batches. Returns elapsed seconds."""
    assert len(chunks) == len(embeddings), "chunks / embeddings length mismatch"
    now = datetime.now(timezone.utc)
    epoch, iso = int(now.timestamp()), now.isoformat(timespec="seconds")
    t0 = time.perf_counter()
    for s in range(0, len(chunks), batch_size):
        part = chunks[s:s + batch_size]
        col.add(ids=[c["id"] for c in part],
                documents=[c["text"] for c in part],
                embeddings=embeddings[s:s + batch_size].astype(np.float32).tolist(),
                metadatas=[chunk_metadata(c, epoch, iso) for c in part])
    return time.perf_counter() - t0


def search(col, query_vec: np.ndarray, k: int = 5, where: Optional[Dict] = None,
           include: Optional[List[str]] = None):
    """Nearest-neighbour search with a pre-computed query vector."""
    return col.query(query_embeddings=[np.asarray(query_vec, dtype=np.float32).tolist()],
                     n_results=k, where=where,
                     include=include or ["documents", "metadatas", "distances"])


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------
def cmd_build(args):
    chunks = [json.loads(l) for l in open(args.chunks, encoding="utf-8")]
    embs = np.load(args.embeddings)
    ids = json.loads(Path(args.embeddings).with_name("chunk_ids.json").read_text())
    assert ids == [c["id"] for c in chunks], "chunk_ids.json does not match chunks.jsonl order"

    client = chromadb.PersistentClient(path=args.db)
    col = create_collection(client, args.collection, args.M, args.ef_construction, args.ef_search)
    print(f"Created '{args.collection}' via {COLLECTION_API} API "
          f"(M={args.M}, ef_construction={args.ef_construction}, ef_search={args.ef_search}, cosine)")
    secs = add_chunks(col, chunks, embs)
    print(f"Ingested {col.count()} chunks ({embs.shape[1]}-d) in {secs:.2f}s; "
          f"db size on disk ~{dir_size_mb(args.db):.1f} MB")
    assert col.count() == len(chunks), "stored count != chunk count"


def cmd_query(args):
    from embed import load_model
    model = load_model()
    client = chromadb.PersistentClient(path=args.db)
    col = client.get_collection(args.collection, embedding_function=None)
    where = {"doc_type": args.doc_type} if args.doc_type else None
    print(f"Collection '{args.collection}': {col.count()} chunks. Type a question, or 'quit'.\n")

    # warm-up so the first timed query isn't paying one-off index/model load cost
    for _ in range(3):
        search(col, model.encode("warm up", normalize_embeddings=True), k=args.k)

    def run(q: str):
        t0 = time.perf_counter()
        qv = model.encode(q, normalize_embeddings=True)
        t1 = time.perf_counter()
        res = search(col, qv, k=args.k, where=where)
        t2 = time.perf_counter()
        print(f"\nencode: {(t1 - t0) * 1000:.1f} ms | vector search: {(t2 - t1) * 1000:.2f} ms")
        for rank, (cid, doc, meta, dist) in enumerate(zip(res["ids"][0], res["documents"][0],
                                                          res["metadatas"][0], res["distances"][0]), 1):
            preview = doc.replace("\n", " ")[:160]
            print(f"[{rank}] sim={1 - dist:.3f}  {cid}  ({meta['chunk_type']}, {meta['section']})\n"
                  f"     {preview}...")
        print()

    if args.q:
        run(args.q)
        return
    while True:
        try:
            q = input("Query> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if q.lower() in {"quit", "exit", "q"}:
            break
        if q:
            run(q)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="create the collection and ingest all chunks")
    b.add_argument("--chunks", default=str(RESULTS / "chunks.jsonl"))
    b.add_argument("--embeddings", default=str(RESULTS / "embeddings.npy"))
    b.add_argument("--db", default=DB_PATH)
    b.add_argument("--collection", default=COLLECTION)
    b.add_argument("--M", type=int, default=DEFAULTS["M"])
    b.add_argument("--ef-construction", type=int, default=DEFAULTS["ef_construction"])
    b.add_argument("--ef-search", type=int, default=DEFAULTS["ef_search"])
    b.set_defaults(fn=cmd_build)

    q = sub.add_parser("query", help="interactive similarity search with latency printout")
    q.add_argument("--db", default=DB_PATH)
    q.add_argument("--collection", default=COLLECTION)
    q.add_argument("--k", type=int, default=5)
    q.add_argument("--q", default=None, help="run a single query and exit")
    q.add_argument("--doc-type", default=None, help="metadata filter: SPEC | SOP | SUP")
    q.set_defaults(fn=cmd_query)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
