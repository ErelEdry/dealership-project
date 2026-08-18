"""
Retrieval evaluation harness.
------------------------------
Scores the semantic-search endpoint on a labelled query set and compares
pure vector search (ANN) against the hybrid lexical rerank.

Relevance is predicate-based (see golden_queries.json): a result is relevant
if its segment/body/fuel is in the allowed set and its price is within the
stated percentile band — a scalable, explainable proxy for human judgment,
evaluated over available stock (the search default).

Metrics: precision@k, recall@k, MRR, nDCG@k (binary relevance).

Run (stack must be up):
    docker compose exec api python -m eval.run_eval
    docker compose exec api python -m eval.run_eval --k 10 --detail
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import httpx
from sqlalchemy import bindparam, create_engine, text

from app.core.config import settings

API = "http://localhost:8000/api/search"
GOLDEN = Path(__file__).parent / "golden_queries.json"


# ── Relevance predicate ──────────────────────────────────────
def is_relevant(vehicle: dict, spec: dict, price_threshold: float | None) -> bool:
    if "segments" in spec and vehicle.get("ai_segment") not in spec["segments"]:
        return False
    if "bodies" in spec and vehicle.get("body_type") not in spec["bodies"]:
        return False
    if "fuels" in spec and vehicle.get("fuel_type") not in spec["fuels"]:
        return False
    if price_threshold is not None and (vehicle.get("price") or 0) > price_threshold:
        return False
    return True


def total_relevant(engine, spec: dict, price_threshold: float | None) -> int:
    """Count relevant vehicles in available stock (denominator for recall)."""
    clauses = ["stock_status = 'available'"]
    params: dict = {}
    for field, col in (("segments", "ai_segment"), ("bodies", "body_type"),
                       ("fuels", "fuel_type")):
        if field in spec:
            clauses.append(f"{col} IN :{field}")
            params[field] = spec[field]
    if price_threshold is not None:
        clauses.append("price <= :price_thr")
        params["price_thr"] = price_threshold

    stmt = text(f"SELECT count(*) FROM vehicle_inventory WHERE {' AND '.join(clauses)}")
    for field in ("segments", "bodies", "fuels"):
        if field in params:
            stmt = stmt.bindparams(bindparam(field, expanding=True))
    with engine.connect() as conn:
        return conn.execute(stmt, params).scalar_one()


def price_at_pctile(engine, pctile: float) -> float:
    with engine.connect() as conn:
        return conn.execute(text(
            "SELECT percentile_cont(:p) WITHIN GROUP (ORDER BY price) "
            "FROM vehicle_inventory WHERE stock_status = 'available'"
        ), {"p": pctile}).scalar_one()


# ── Metrics (binary relevance) ───────────────────────────────
def precision_at_k(rels: list[bool], k: int) -> float:
    top = rels[:k]
    return sum(top) / k if top else 0.0


def recall_at_k(rels: list[bool], k: int, total: int) -> float:
    return sum(rels[:k]) / total if total else 0.0


def reciprocal_rank(rels: list[bool]) -> float:
    for i, r in enumerate(rels, start=1):
        if r:
            return 1.0 / i
    return 0.0


def ndcg_at_k(rels: list[bool], k: int, total: int) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, r in enumerate(rels[:k], start=1) if r)
    ideal_hits = min(k, total)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def search(client: httpx.Client, query: str, k: int, rerank: bool) -> list[dict]:
    resp = client.post(API, json={
        "query": query, "limit": k, "rerank": rerank, "stock_status": "available",
    })
    resp.raise_for_status()
    return [hit["vehicle"] for hit in resp.json()["results"]]


def main(k: int, detail: bool) -> None:
    sync_url = settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2")
    engine = create_engine(sync_url, pool_pre_ping=True)
    golden = json.loads(GOLDEN.read_text())["queries"]

    modes = {"ANN only": False, "Hybrid rerank": True}
    agg = {m: {"p5": [], "pk": [], "rk": [], "mrr": [], "ndcg": []} for m in modes}
    k5 = min(5, k)

    with httpx.Client(timeout=30) as client:
        for spec in golden:
            q = spec["query"]
            thr = price_at_pctile(engine, spec["price_pctile"]) if "price_pctile" in spec else None
            total = total_relevant(engine, spec, thr)

            if detail:
                print(f"\n· {q!r}  (relevant in stock: {total})")
            for mode, rerank in modes.items():
                vehicles = search(client, q, k, rerank)
                rels = [is_relevant(v, spec, thr) for v in vehicles]
                a = agg[mode]
                a["p5"].append(precision_at_k(rels, k5))
                a["pk"].append(precision_at_k(rels, k))
                a["rk"].append(recall_at_k(rels, k, total))
                a["mrr"].append(reciprocal_rank(rels))
                a["ndcg"].append(ndcg_at_k(rels, k, total))
                if detail:
                    print(f"    {mode:14} P@{k5}={precision_at_k(rels, k5):.2f} "
                          f"P@{k}={precision_at_k(rels, k):.2f} "
                          f"RR={reciprocal_rank(rels):.2f}")

    def mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    print(f"\n{'=' * 62}\nRetrieval eval over {len(golden)} queries (k={k})\n{'=' * 62}")
    print(f"{'':16}{'P@'+str(k5):>8}{'P@'+str(k):>8}{'R@'+str(k):>8}"
          f"{'MRR':>8}{'nDCG@'+str(k):>9}")
    for mode in modes:
        a = agg[mode]
        print(f"{mode:16}{mean(a['p5']):>8.3f}{mean(a['pk']):>8.3f}"
              f"{mean(a['rk']):>8.3f}{mean(a['mrr']):>8.3f}{mean(a['ndcg']):>9.3f}")

    base, hyb = agg["ANN only"], agg["Hybrid rerank"]
    print(f"{'Δ (rerank)':16}{mean(hyb['p5']) - mean(base['p5']):>+8.3f}"
          f"{mean(hyb['pk']) - mean(base['pk']):>+8.3f}"
          f"{mean(hyb['rk']) - mean(base['rk']):>+8.3f}"
          f"{mean(hyb['mrr']) - mean(base['mrr']):>+8.3f}"
          f"{mean(hyb['ndcg']) - mean(base['ndcg']):>+9.3f}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Retrieval evaluation harness")
    ap.add_argument("--k", type=int, default=10, help="cutoff k (default 10)")
    ap.add_argument("--detail", action="store_true", help="per-query breakdown")
    main(ap.parse_args().k, ap.parse_args().detail)
