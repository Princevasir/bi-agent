"""Retrieval evaluation (RAG R5): does knowledge search return the right documents?

    cd backend && .venv/bin/python -m evals.retrieval [--k 5]

Runs every labelled question in retrieval_cases.json through the real retrieval (real embedder,
real index, the case's role) and reports Recall@K, Precision@K, MRR and latency. Ranking is by
document: the first chunk of each document counts, later chunks of the same document are skipped.
"""
import argparse
import json
import os
import statistics
import time
from pathlib import Path

from app.knowledge.retrieval import retrieve

CASES = Path(__file__).resolve().parent / "retrieval_cases.json"
LOCAL_APP_DB = "postgresql://app_rw:app_dev_pw@localhost:5433/appdb"


def recall_at_k(ranked, relevant, k):
    return len(set(ranked[:k]) & set(relevant)) / len(relevant)


def precision_at_k(ranked, relevant, k):
    return len(set(ranked[:k]) & set(relevant)) / k


def reciprocal_rank(ranked, relevant):
    return next((1 / (i + 1) for i, doc in enumerate(ranked) if doc in relevant), 0.0)


def ranked_documents(hits):
    return list(dict.fromkeys(h.document_id for h in hits))


def evaluate(cases, k, search):
    rows = []
    for case in cases:
        start = time.perf_counter()
        hits = search(case["question"], case.get("role", "analyst"))
        ms = (time.perf_counter() - start) * 1000
        ranked = ranked_documents(hits)
        relevant = set(case["relevant"])
        rows.append({"id": case["id"], "ranked": ranked[:k], "recall": recall_at_k(ranked, relevant, k),
                     "precision": precision_at_k(ranked, relevant, k), "rr": reciprocal_rank(ranked, relevant),
                     "top_score": hits[0].score if hits else 0.0, "ms": ms, "relevant": sorted(relevant)})
    return rows


def summary(rows):
    return {"recall": statistics.mean(r["recall"] for r in rows),
            "precision": statistics.mean(r["precision"] for r in rows),
            "mrr": statistics.mean(r["rr"] for r in rows),
            "hit_rate": statistics.mean(1.0 if r["rr"] else 0.0 for r in rows),
            "p50_ms": statistics.median(r["ms"] for r in rows),
            "p95_ms": sorted(r["ms"] for r in rows)[int(0.95 * (len(rows) - 1))]}


def main(argv=None):
    p = argparse.ArgumentParser(description="Evaluate knowledge retrieval.")
    p.add_argument("--k", type=int, default=5)
    args = p.parse_args(argv)
    os.environ.setdefault("APP_DATABASE_URL", LOCAL_APP_DB)
    cases = json.loads(CASES.read_text())["cases"]
    # Fetch more chunks than K so that K distinct documents can be ranked.
    rows = evaluate(cases, args.k, lambda q, role: retrieve(q, role, top_k=args.k * 3, min_similarity=0,
                                                           max_context_tokens=10**6))
    for r in rows:
        mark = "ok  " if r["rr"] == 1 else ("weak" if r["rr"] else "MISS")
        print(f"{mark} {r['id']:<20} RR {r['rr']:.2f} recall {r['recall']:.2f} top {r['top_score']:.3f}  {r['ranked'][:3]}")
    s = summary(rows)
    print(f"\n{len(rows)} questions, K={args.k}: Recall@K {s['recall']:.3f}, Precision@K {s['precision']:.3f}, "
          f"MRR {s['mrr']:.3f}, found at all {s['hit_rate']:.3f}, latency p50 {s['p50_ms']:.0f} ms, p95 {s['p95_ms']:.0f} ms")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
