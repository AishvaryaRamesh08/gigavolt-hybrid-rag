#!/usr/bin/env python3
"""
benchmark.py - Phase 4 HNSW benchmark (headless; no Jupyter needed).

Run after chunker.py + embed.py have produced results/chunks.jsonl and
results/embeddings.npy.  From the project root:

    python src/benchmark.py             # full grid (~5,000-vector corpus)
    python src/benchmark.py --quick     # small/fast sanity run

What it does
  1. Loads the real corpus and grows it to --scale-target vectors (real incident reports from
     the class script + labelled synthetic recombinations) so HNSW tuning is informative.
  2. Builds a query set (hand-written questions + sampled spans) and computes EXACT top-5
     ground truth by brute-force cosine similarity.
  3. Sweeps HNSW M x ef_construction x ef_search; per config measures build time, latency
     (P50/P95/P99, search only) and recall@1 / recall@5 against the exact results.
  4. Picks the cheapest config meeting the latency and recall targets.
  5. Checks relevance (hit@k) on the REAL corpus only.
  6. Writes to results/: hnsw_grid_results.csv, hnsw_tradeoffs.png, latency_distribution.png,
     relevance_results.csv, benchmark_report.md  (and prints the key tables + an ASCII histogram).
"""

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")                       # headless: write PNGs, never open a window
import matplotlib.pyplot as plt

import chromadb
import embed
import scale_corpus as sc
import vectordb as vdb
from paths import INCIDENTS, RESULTS

K = 5

HAND_QUERIES = [
    ("Which fault codes qualify for cell manufacturing defect warranty coverage?", "GV-SOP-WAR-101"),
    ("What happens to warranty if state of charge stays below 5% for more than 7 days?", "GV-SOP-WAR-101"),
    ("What is the termination resistance of the BMS CAN bus?", "GV-SPEC-BMS-ARC-01"),
    ("What does error ERR_BMS_301 module communication lost mean?", "GV-SPEC-BMS-ARC-01"),
    ("What is the thermal decomposition onset temperature of the LFP cell?", "GV-SPEC-CELL-LFP-08"),
    ("What is the cycle life of the Prismacell 280Ah cell?", "GV-SPEC-CELL-LFP-08"),
    ("What is the pouch swelling limit for the NMC cell?", "GV-SPEC-CELL-NMC-65"),
    ("At what temperature does NMC-811 begin self-heating?", "GV-SPEC-CELL-NMC-65"),
    ("What is the trigger current for the pyrofuse?", "GV-SPEC-FUSE-PYRO-04"),
    ("How do I safely test a pyrofuse bridge circuit?", "GV-SPEC-FUSE-PYRO-04"),
    ("What conductivity requires replacing the glycol filter cartridge?", "GV-SPEC-THERM-GLY-02"),
    ("What pH means the coolant must be flushed and refilled?", "GV-SPEC-THERM-GLY-02"),
    ("What non-conformances were found at the SinoPower slitting line?", "GV-SUP-AUD-502"),
    ("What was the SinoPower audit score?", "GV-SUP-AUD-502"),
    ("Who supplies the cathode precursor for the Megapack X-7000?", "GV-SUP-REP-401"),
    ("What do we do when ERR_BMS_701 exceeds 3.5% across a batch?", "GV-SUP-REP-401"),
    ("Which components are single-source risks and who is the second source?", "GV-SUP-REP-409"),
    ("Which supplier was quarantined under incident INC-2024-088?", "GV-SUP-REP-409"),
    ("Which retrofit kit fixes ERR_INV_404 on older Megapack units?", "GV-ECO-2024-019"),
    ("What replaced the brass pressure relief valve in the chiller glycol manifold?", "GV-ECO-2024-031"),
    ("What torque is required for the C-1200 cassette mounting ear fasteners?", "GV-ECO-2024-044"),
    ("Why was the G-3500 cabinet door gasket changed to EPDM?", "GV-ECO-2024-052"),
    ("What was the root cause of the thermal runaway at the Bakersfield facility?", "GV-INC-2024-088"),
    ("Why did the main contactor weld closed at the Rio Bravo plant?", "GV-INC-2024-104"),
    ("How did rodents cause the arc flash at Northlake Peaking Station?", "GV-INC-2024-119"),
    ("What arc flash PPE category is required to service the G-3500?", "GV-MAN-G3500-002"),
    ("How do I extract a cassette from the C-1200?", "GV-MAN-C1200-003"),
    ("How often is coolant conductivity tested on the X-7000?", "GV-MAN-X7000-001"),
    ("What voltage deviation is allowed when calibrating the cell voltage sense harness?", "GV-SOP-CAL-420"),
    ("How fast must pre-charge reach 95% of open-circuit voltage during site acceptance testing?", "GV-SOP-COMM-201"),
    ("What cell voltage must LFP systems be discharged to before decommissioning?", "GV-SOP-DECOM-601"),
    ("How long does flashing the master controller firmware take?", "GV-SOP-FIRM-105"),
    ("What is the refrigerant charge of the G-3500 chiller?", "GV-SOP-HVAC-310"),
    ("What happens in Stage 3 of the emergency escalation protocol?", "GV-SOP-SAFETY-900"),
    ("How long must a site be certified cold before technicians re-enter after a fire?", "GV-SOP-SAFETY-900"),
]


# --------------------------------------------------------------------------
# small utilities
# --------------------------------------------------------------------------
def log(msg: str):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def md_table(df: pd.DataFrame) -> str:
    def fmt(v):
        return f"{v:.3f}" if isinstance(v, (float, np.floating)) else str(v)
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "|".join("---" for _ in df.columns) + "|"]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(fmt(v) for v in r) + " |")
    return "\n".join(lines)


def ascii_hist(values, bins=14, width=44) -> str:
    counts, edges = np.histogram(values, bins=bins)
    peak = max(counts.max(), 1)
    out = []
    for c, lo, hi in zip(counts, edges[:-1], edges[1:]):
        out.append(f"{lo:7.2f}-{hi:7.2f} ms | {'#' * int(width * c / peak):<{width}} {c}")
    return "\n".join(out)


# --------------------------------------------------------------------------
# corpus + queries
# --------------------------------------------------------------------------
def load_real(results: Path):
    chunks = [json.loads(l) for l in open(results / "chunks.jsonl", encoding="utf-8")]
    embs = np.load(results / "embeddings.npy")
    ids = json.loads((results / "chunk_ids.json").read_text())
    if ids != [c["id"] for c in chunks] or len(ids) != len(embs):
        sys.exit("chunks.jsonl / embeddings.npy / chunk_ids.json are out of sync - rerun chunker.py and embed.py")
    return chunks, embs


def build_bench_corpus(real_chunks, real_embs, model, args, results: Path):
    extra = []
    if not args.no_incidents:
        extra += sc.load_incident_reports(args.incident_src)
    if args.service_records:
        extra += sc.load_service_records(args.service_sql)
    extra += sc.synthesize_chunks(real_chunks + extra, args.scale_target, seed=args.seed)
    bench = real_chunks + extra

    cache_e, cache_i = results / "bench_embeddings.npy", results / "bench_ids.json"
    ids = [c["id"] for c in bench]
    if cache_e.exists() and cache_i.exists() and json.loads(cache_i.read_text()) == ids:
        log(f"using cached benchmark embeddings ({len(ids)} vectors)")
        embs = np.load(cache_e)
    else:
        log(f"embedding {len(extra)} extra chunks (one-off, cached afterwards) ...")
        t0 = time.perf_counter()
        e_extra = embed.embed_texts([c["embed_text"] for c in extra], model, batch_size=args.embed_batch, verbose=False)
        embs = np.vstack([real_embs, e_extra]).astype(np.float32)
        np.save(cache_e, embs)
        cache_i.write_text(json.dumps(ids))
        log(f"  done in {time.perf_counter() - t0:.1f}s")
    assert len(set(ids)) == len(ids), "duplicate chunk ids in benchmark corpus"
    return bench, embs


def sampled_queries(chunks, n, rng):
    out = []
    for i in rng.choice(len(chunks), n, replace=True):
        words = chunks[i]["text"].split()
        start = int(rng.integers(0, max(1, len(words) - 12)))
        piece = words[start:start + int(rng.integers(8, 16))]
        kept = [w for w in piece if rng.random() > 0.15]
        out.append(" ".join(kept or piece))
    return out


# --------------------------------------------------------------------------
# benchmark core
# --------------------------------------------------------------------------
def recall_at(found, gt, k):
    return float(np.mean([len(set(f[:k]) & set(g[:k])) / k for f, g in zip(found, gt)]))


def measure(col, qvecs, id2idx, warmup=20):
    for q in qvecs[:warmup]:
        vdb.search(col, q, k=K, include=["distances"])
    lat, found = [], []
    for q in qvecs:
        t = time.perf_counter()
        r = vdb.search(col, q, k=K, include=["distances"])
        lat.append((time.perf_counter() - t) * 1000)
        found.append([id2idx[i] for i in r["ids"][0]])
    return np.array(lat), found


def run_grid(client, bench, E, QE, GT, id2idx, db_dir, m_vals, efc_vals, efs_vals):
    """One collection per (M, ef_construction, ef_search): ef_search changed in place did not take effect."""
    rows, latencies = [], {}
    total = len(m_vals) * len(efc_vals)
    n = 0
    for M in m_vals:
        for efc in efc_vals:
            n += 1
            first = len(rows)
            for efs in efs_vals:
                name = f"bench_M{M}_efc{efc}_efs{efs}"
                before = vdb.dir_size_mb(str(db_dir))
                col = vdb.create_collection(client, name, M, efc, efs)
                build_s = vdb.add_chunks(col, bench, E)
                size_mb = vdb.dir_size_mb(str(db_dir)) - before
                lat, found = measure(col, QE, id2idx)
                latencies[(M, efc, efs)] = lat
                rows.append(dict(M=M, ef_construction=efc, ef_search=efs, build_s=round(build_s, 2),
                                 index_mb=round(size_mb, 1),
                                 p50_ms=float(np.percentile(lat, 50)), p95_ms=float(np.percentile(lat, 95)),
                                 p99_ms=float(np.percentile(lat, 99)), mean_ms=float(lat.mean()),
                                 recall_at_1=recall_at(found, GT, 1), recall_at_5=recall_at(found, GT, 5)))
                client.delete_collection(name)               # free memory/disk before the next build
            last = rows[first:]
            log(f"[{n}/{total}] M={M:>2} efc={efc:>3}  "
                f"recall@5 by ef_search {[round(r['recall_at_5'], 3) for r in last]}  "
                f"p50 {min(r['p50_ms'] for r in last):.2f}-{max(r['p50_ms'] for r in last):.2f} ms")
    return pd.DataFrame(rows), latencies


def choose(df, latency_target, recall_target):
    for r in (recall_target, 0.90):
        ok = df[(df.p50_ms < latency_target) & (df.recall_at_5 >= r)]
        if len(ok):
            return ok.sort_values(["p50_ms", "build_s"]).iloc[0], r
    return df.sort_values("recall_at_5", ascending=False).iloc[0], None


# --------------------------------------------------------------------------
# plots
# --------------------------------------------------------------------------
def plot_tradeoffs(df, m_vals, efc_vals, path):
    colors = dict(zip(m_vals, ["tab:red", "tab:orange", "tab:green", "tab:blue", "tab:purple", "tab:brown"]))
    fig, ax = plt.subplots(2, 2, figsize=(14, 10))
    for efc, ls in [(efc_vals[-1], "-"), (efc_vals[0], "--")]:
        for M in m_vals:
            s = df[(df.M == M) & (df.ef_construction == efc)].sort_values("ef_search")
            ax[0, 0].plot(s.ef_search, s.recall_at_5, ls, marker="o", color=colors[M], label=f"M={M}, efc={efc}")
            ax[0, 1].plot(s.ef_search, s.p50_ms, ls, marker="o", color=colors[M], label=f"M={M}, efc={efc}")
    ax[0, 0].axhline(0.9, color="k", ls=":"); ax[0, 0].set(title="Recall@5 vs ef_search", xlabel="ef_search", ylabel="recall@5", xscale="log")
    ax[0, 1].axhline(20, color="k", ls=":"); ax[0, 1].set(title="Median latency vs ef_search (dotted = 20 ms)", xlabel="ef_search", ylabel="p50 (ms)", xscale="log")
    ax[0, 0].legend(fontsize=7); ax[0, 1].legend(fontsize=7)
    ax[1, 0].scatter(df.p50_ms, df.recall_at_5, c=[colors[m] for m in df.M], s=20 + df.ef_search)
    ax[1, 0].axhline(0.9, color="k", ls=":"); ax[1, 0].axvline(20, color="k", ls=":")
    ax[1, 0].set(title="Latency vs recall (every config; size ~ ef_search)", xlabel="p50 latency (ms)", ylabel="recall@5")
    b = df.drop_duplicates(["M", "ef_construction"]).pivot(index="M", columns="ef_construction", values="build_s")
    b.plot.bar(ax=ax[1, 1]); ax[1, 1].set(title="Index build time", ylabel="seconds", xlabel="M"); ax[1, 1].tick_params(axis="x", rotation=0)
    plt.tight_layout(); plt.savefig(path, dpi=150); plt.close(fig)


def plot_latency(lat, pct, title, efs_vals, latencies, cM, cEFC, path):
    fig, a = plt.subplots(1, 2, figsize=(13, 4))
    a[0].hist(lat, bins=40, color="tab:blue", alpha=.8)
    for name, c in [("P50", "green"), ("P95", "orange"), ("P99", "red")]:
        a[0].axvline(pct[name], color=c, ls="--", label=f"{name} {pct[name]:.2f} ms")
    a[0].set(title=title, xlabel="ms", ylabel="queries"); a[0].legend()
    a[1].boxplot([latencies[(cM, cEFC, e)] for e in efs_vals], showfliers=False); a[1].set_xticklabels(efs_vals)
    a[1].set(title="Latency by ef_search (chosen M, efc)", xlabel="ef_search", ylabel="ms")
    plt.tight_layout(); plt.savefig(path, dpi=150); plt.close(fig)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--results", default=str(RESULTS))
    ap.add_argument("--scale-target", type=int, default=5000, help="total vectors in the benchmark corpus")
    ap.add_argument("--n-sampled", type=int, default=300, help="number of sampled queries")
    ap.add_argument("--m-values", type=int, nargs="+", default=[4, 8, 16, 32])
    ap.add_argument("--efc-values", type=int, nargs="+", default=[50, 200])
    ap.add_argument("--efs-values", type=int, nargs="+", default=[5, 10, 25, 50, 100])
    ap.add_argument("--latency-target", type=float, default=20.0)
    ap.add_argument("--recall-target", type=float, default=0.95)
    ap.add_argument("--embed-batch", type=int, default=16, help="lower if the process gets Killed (low RAM)")
    ap.add_argument("--no-incidents", action="store_true", help="skip the 100 class-script incident reports")
    ap.add_argument("--incident-src", default=str(INCIDENTS))
    ap.add_argument("--service-records", action="store_true", help="also load ERP service text from MariaDB")
    ap.add_argument("--service-sql", default="SELECT service_log_id, full_service_context FROM Service_Logs "
                                             "WHERE full_service_context IS NOT NULL")
    ap.add_argument("--quick", action="store_true", help="small fast run: 2,000 vectors, reduced grid")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    if args.quick:
        args.scale_target, args.n_sampled = 2000, 150
        args.m_values, args.efc_values, args.efs_values = [8, 16], [100], [10, 50, 100]

    results = Path(args.results); results.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    t_start = time.perf_counter()
    log(f"chromadb {chromadb.__version__}")

    # 1. corpus
    real_chunks, E_real = load_real(results)
    log(f"loading embedding model ...")
    model = embed.load_model()
    bench, E = build_bench_corpus(real_chunks, E_real, model, args, results)
    ids = [c["id"] for c in bench]
    id2idx = {cid: i for i, cid in enumerate(ids)}
    types = pd.Series([c["chunk_type"] for c in bench]).value_counts()
    log(f"benchmark corpus: {E.shape[0]} vectors ({', '.join(f'{k}={v}' for k, v in types.items())})")

    # 2. queries + exact ground truth
    all_queries = [q for q, _ in HAND_QUERIES] + sampled_queries(bench, args.n_sampled, rng)
    QE = embed.embed_texts(all_queries, model, batch_size=args.embed_batch, verbose=False)
    enc_ms = []
    for q in all_queries[:60]:
        t = time.perf_counter(); model.encode(q, normalize_embeddings=True, show_progress_bar=False)
        enc_ms.append((time.perf_counter() - t) * 1000)
    encode_p50 = float(np.percentile(enc_ms, 50))
    GT = np.argsort(-(QE @ E.T), axis=1)[:, :K]
    log(f"{len(all_queries)} queries; single-query encode p50 = {encode_p50:.1f} ms; exact ground truth ready")

    # 3. HNSW grid
    db_dir = results / "vectordb_bench"
    if db_dir.exists():
        shutil.rmtree(db_dir, ignore_errors=True)
    client = chromadb.PersistentClient(path=str(db_dir))
    log(f"HNSW grid: M={args.m_values} efc={args.efc_values} ef_search={args.efs_values}")
    df, latencies = run_grid(client, bench, E, QE, GT, id2idx, db_dir,
                             args.m_values, args.efc_values, args.efs_values)
    df.to_csv(results / "hnsw_grid_results.csv", index=False)
    log(f"Chroma index-config API used: {vdb.COLLECTION_API}")
    plot_tradeoffs(df, args.m_values, args.efc_values, results / "hnsw_tradeoffs.png")

    # 4. choose config + latency distribution
    chosen, used_recall = choose(df, args.latency_target, args.recall_target)
    cM, cEFC, cEFS = int(chosen.M), int(chosen.ef_construction), int(chosen.ef_search)
    met = chosen.p50_ms < args.latency_target and chosen.recall_at_5 > 0.9
    lat = latencies[(cM, cEFC, cEFS)]
    pct = {f"P{p}": float(np.percentile(lat, p)) for p in (50, 90, 95, 99)}
    pct.update(min=float(lat.min()), max=float(lat.max()))
    plot_latency(lat, pct, f"Search latency (M={cM}, efc={cEFC}, ef_search={cEFS}, n={len(lat)})",
                 args.efs_values, latencies, cM, cEFC, results / "latency_distribution.png")

    bf = []
    for q in QE:
        t = time.perf_counter(); np.argpartition(-(E @ q), K)[:K]; bf.append((time.perf_counter() - t) * 1000)
    bf_p50 = float(np.percentile(bf, 50))

    # 5. relevance on the REAL corpus only
    col_real = vdb.create_collection(client, "gigavolt_docs_real", cM, cEFC, cEFS)
    vdb.add_chunks(col_real, real_chunks, E_real)
    rel = []
    for (q, expected), qv in zip(HAND_QUERIES, QE[:len(HAND_QUERIES)]):
        r = vdb.search(col_real, qv, k=5, include=["metadatas"])
        docs = [m["doc_id"] for m in r["metadatas"][0]]
        rank = docs.index(expected) + 1 if expected in docs else None
        rel.append(dict(query=q, expected=expected, rank=rank, top1=docs[0]))
    rel = pd.DataFrame(rel)
    rel.to_csv(results / "relevance_results.csv", index=False)
    hits = {k: float((rel["rank"].fillna(99) <= k).mean()) for k in (1, 3, 5)}

    # 6. report
    grid_view = df.round(3).sort_values(["M", "ef_construction", "ef_search"]).reset_index(drop=True)
    pct_df = pd.DataFrame({"metric": list(pct), "search_only_ms": [round(v, 3) for v in pct.values()]})
    misses = rel[rel["rank"].isna()][["query", "expected", "top1"]]
    report = f"""# Phase 4 - HNSW benchmark report

Generated {time.strftime('%Y-%m-%d %H:%M:%S')} | chromadb {chromadb.__version__} (index API: {vdb.COLLECTION_API}) | model all-MiniLM-L6-v2

## Corpus
- Real chunks: {len(real_chunks)} from {len({c['doc_id'] for c in real_chunks})} documents
- Benchmark corpus: {E.shape[0]} vectors ({', '.join(f'{k}={v}' for k, v in types.items())}); synthetic chunks are used for latency/recall only
- Queries: {len(HAND_QUERIES)} hand-written + {args.n_sampled} sampled = {len(all_queries)}

## Chosen configuration
M = {cM}, ef_construction = {cEFC}, ef_search = {cEFS}
(rule: lowest p50 with p50 < {args.latency_target:g} ms and recall@5 >= {used_recall if used_recall else 'n/a (no config met the targets)'})

| target | result | met |
|---|---|---|
| median search latency < {args.latency_target:g} ms | {chosen.p50_ms:.2f} ms | {'yes' if chosen.p50_ms < args.latency_target else 'NO'} |
| recall@5 > 0.9 | {chosen.recall_at_5:.3f} | {'yes' if chosen.recall_at_5 > 0.9 else 'NO'} |

Single-query encode latency (reported separately): p50 = {encode_p50:.1f} ms; search + encode p50 = {pct['P50'] + encode_p50:.1f} ms.
Exact brute-force (numpy) p50 over the same vectors: {bf_p50:.2f} ms.

## Latency distribution (chosen configuration, search only)
{md_table(pct_df)}

```
{ascii_hist(lat)}
```

## Relevance on the real corpus (hit@k, {len(HAND_QUERIES)} questions)
hit@1 = {hits[1]:.2f}, hit@3 = {hits[3]:.2f}, hit@5 = {hits[5]:.2f}

{('Questions whose expected document was not in the top 5:' + chr(10) + chr(10) + md_table(misses)) if len(misses) else 'Every expected document appeared in the top 5.'}

## Full grid
{md_table(grid_view)}

## Notes / caveats
- Latency = collection.query only, with pre-computed query vectors, 20 warm-up queries discarded, each query timed individually.
- Recall@k compares HNSW results with exact brute-force top-k (cosine on normalised vectors); it measures index fidelity, not relevance.
- Relevance (hit@k) is measured separately on the real corpus without synthetic data.
- At this corpus size brute force is competitive with HNSW; the ANN advantage appears as the corpus grows.
"""
    (results / "benchmark_report.md").write_text(report, encoding="utf-8")

    # console summary (handy for screenshots / the video)
    print("\n" + "=" * 78)
    print(f"CHOSEN: M={cM}  ef_construction={cEFC}  ef_search={cEFS}")
    print(f"  search latency  p50={pct['P50']:.2f} ms  p95={pct['P95']:.2f} ms  p99={pct['P99']:.2f} ms   (target < {args.latency_target:g} ms median)")
    print(f"  encode latency  p50={encode_p50:.1f} ms (reported separately)")
    print(f"  recall@5 = {chosen.recall_at_5:.3f}  recall@1 = {chosen.recall_at_1:.3f}   (target > 0.9)")
    print(f"  relevance hit@1/3/5 = {hits[1]:.2f} / {hits[3]:.2f} / {hits[5]:.2f}   brute-force p50 = {bf_p50:.2f} ms")
    print(f"  TARGETS {'MET' if met else 'NOT MET'}")
    print("-" * 78)
    print("Latency distribution (chosen config):")
    print(ascii_hist(lat))
    print("=" * 78)
    log(f"done in {time.perf_counter() - t_start:.0f}s. Files in {results}/: hnsw_grid_results.csv, "
        f"hnsw_tradeoffs.png, latency_distribution.png, relevance_results.csv, benchmark_report.md")


if __name__ == "__main__":
    main()
