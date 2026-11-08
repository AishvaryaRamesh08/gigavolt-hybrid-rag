"""
embed.py - Phase 4 embedding generation.

Reads results/chunks.jsonl, embeds every chunk's `embed_text` with a local
SentenceTransformers model, and writes:
    results/embeddings.npy   float32 matrix, shape (n_chunks, dim), L2-normalised
    results/chunk_ids.json   ids in the same row order

Why all-MiniLM-L6-v2?  Free, runs on the EC2 CPU with no API latency/cost,
384 dimensions (small + fast HNSW), and reproducible offline for anyone rerunning it.
Trade-off: lower semantic quality than larger/API models (e.g. OpenAI
text-embedding-3-small, 1536-d); for ~hundreds of short technical chunks the
speed/cost/reproducibility win is worth it.

Vectors are normalised so cosine similarity == dot product. That lets the
benchmark compute exact ground truth with a single matrix multiply.

Usage:
    python src/embed.py
"""

import argparse
import json
import time
from pathlib import Path
from typing import List, Optional

import numpy as np

from paths import RESULTS

MODEL_NAME = "all-MiniLM-L6-v2"


def load_model(name: str = MODEL_NAME):
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(name, device="cpu")


def embed_texts(texts: List[str], model=None, batch_size: int = 64,
                normalize: bool = True, verbose: bool = True) -> np.ndarray:
    """Embed texts in batches. A failing batch is retried item-by-item so one bad
    chunk cannot abort the whole run; items that still fail raise at the end."""
    model = model or load_model()
    out: List[Optional[np.ndarray]] = [None] * len(texts)
    failed: List[int] = []
    t0 = time.perf_counter()

    for start in range(0, len(texts), batch_size):
        idx = list(range(start, min(start + batch_size, len(texts))))
        try:
            vecs = model.encode([texts[i] for i in idx], batch_size=batch_size,
                                normalize_embeddings=normalize, show_progress_bar=False)
            for i, v in zip(idx, vecs):
                out[i] = v
        except Exception as exc:
            print(f"  batch {start}-{idx[-1]} failed ({exc.__class__.__name__}); retrying per item")
            for i in idx:
                try:
                    out[i] = model.encode(texts[i][:2000], normalize_embeddings=normalize,
                                          show_progress_bar=False)
                except Exception as exc2:
                    print(f"  item {i} failed: {exc2}")
                    failed.append(i)
        if verbose:
            print(f"  embedded {min(start + batch_size, len(texts))}/{len(texts)}")

    if failed:
        raise RuntimeError(f"{len(failed)} chunk(s) could not be embedded: {failed[:10]}")
    if verbose:
        dt = time.perf_counter() - t0
        print(f"  done in {dt:.1f}s ({len(texts) / max(dt, 1e-9):.0f} chunks/s)")
    return np.asarray(out, dtype=np.float32)


def embedding_dim(model) -> int:
    """sentence-transformers renamed get_sentence_embedding_dimension -> get_embedding_dimension."""
    fn = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    return fn()


def count_truncated(texts: List[str], model) -> int:
    """How many inputs exceed the model's max sequence length (they would be silently cut)."""
    tok = getattr(model, "tokenizer", None)
    if tok is None:
        return 0
    limit = model.max_seq_length
    return sum(1 for t in texts if len(tok.encode(t, add_special_tokens=True)) > limit)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--chunks", default=str(RESULTS / "chunks.jsonl"))
    ap.add_argument("--out", default=str(RESULTS))
    ap.add_argument("--model", default=MODEL_NAME)
    ap.add_argument("--batch-size", type=int, default=32,
                    help="lower (e.g. 8) if the process gets Killed on a small-memory instance")
    args = ap.parse_args()

    chunks = [json.loads(line) for line in open(args.chunks, encoding="utf-8")]
    texts = [c["embed_text"] for c in chunks]
    print(f"Loaded {len(chunks)} chunks; loading model {args.model} ...")

    model = load_model(args.model)
    print(f"Model max_seq_length = {model.max_seq_length} tokens, "
          f"dimension = {embedding_dim(model)}")
    n_trunc = count_truncated(texts, model)
    print(f"Chunks exceeding max_seq_length (would be truncated): {n_trunc}")

    embs = embed_texts(texts, model, batch_size=args.batch_size)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "embeddings.npy", embs)
    (out / "chunk_ids.json").write_text(json.dumps([c["id"] for c in chunks]))
    print(f"Saved {embs.shape} float32 matrix -> {out / 'embeddings.npy'} "
          f"({embs.nbytes / 1024:.0f} KiB)")


if __name__ == "__main__":
    main()
