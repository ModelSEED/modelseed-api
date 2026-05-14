"""Compare a RAST-built model against a BV-BRC-built model of the same organism.

The point: prove that our RAST-to-KBase-Genome translator produces a model
biologically equivalent to what we'd get if the same organism had been
annotated by BV-BRC instead. Differences should be within the tolerance
expected from two independent annotation pipelines, not so large they
suggest the translator is dropping or mistranslating data.

What it does:
  1. Submits two reconstruct jobs in parallel against the deployed API
     (BV-BRC path + RAST-job path)
  2. Polls until both complete
  3. Fetches both models
  4. Reports a side-by-side stats table + parity verdicts

Usage:
  export PATRIC_TOKEN=<your patric token>
  export RAST_TOKEN=<your rast token>
  python scripts/compare_rast_vs_bvbrc.py \\
      --bvbrc-genome 871585.3 \\
      --rast-job 1670911 \\
      --rast-genome 871585.30 \\
      --display-name "Acinetobacter pittii PHEA-2"

Tokens are read from env vars; never put them on the command line.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

API = os.environ.get("MODELSEED_API_URL", "https://modelseed.org/PMS")


def _client(token: str, *, timeout: float = 180.0) -> httpx.Client:
    return httpx.Client(
        base_url=API,
        headers={"Authorization": token},
        timeout=httpx.Timeout(timeout, connect=10.0),
        follow_redirects=True,
    )


def _submit_bvbrc(client: httpx.Client, genome_id: str, output_path: str) -> str:
    r = client.post(
        "/api/jobs/reconstruct",
        json={
            "genome": genome_id,
            "template_type": "auto",
            "atp_safe": True,
            "gapfill": False,
            "output_path": output_path,
        },
    )
    r.raise_for_status()
    return r.json()


def _submit_rast(
    client: httpx.Client,
    display_name: str,
    rast_job_id: str,
    rast_genome_id: str,
    output_path: str,
) -> str:
    r = client.post(
        "/api/jobs/reconstruct",
        json={
            "genome": display_name,
            "rast_job_id": rast_job_id,
            "rast_genome_id": rast_genome_id,
            "template_type": "auto",
            "atp_safe": True,
            "gapfill": False,
            "output_path": output_path,
        },
    )
    r.raise_for_status()
    return r.json()


def _poll_job(client: httpx.Client, job_id: str, *, timeout_s: int = 1500) -> dict:
    """Poll until terminal status. Returns the job record."""
    deadline = time.monotonic() + timeout_s
    last_repr = ""
    while time.monotonic() < deadline:
        r = client.get("/api/jobs", params={"ids": job_id})
        r.raise_for_status()
        rec = r.json().get(job_id) or {}
        status = rec.get("status")
        rep = f"{status} | {rec.get('progress') or rec.get('error') or ''}"
        if rep != last_repr:
            print(f"  [{time.strftime('%H:%M:%S')}] {job_id[:8]}: {rep}")
            last_repr = rep
        if status in {"completed", "failed"}:
            return rec
        time.sleep(20)
    raise TimeoutError(f"job {job_id} did not finish within {timeout_s}s")


def _fetch_model(client: httpx.Client, ref: str) -> dict:
    r = client.get("/api/models/data", params={"ref": ref})
    r.raise_for_status()
    return r.json()


def _stats(model: dict) -> dict:
    rxns = model.get("reactions") or []
    cpds = model.get("compounds") or []
    genes = model.get("genes") or []
    bios = model.get("biomasses") or []
    with_gpr = sum(1 for r in rxns if (r.get("gpr") or "").strip())
    return {
        "reactions": len(rxns),
        "compounds": len(cpds),
        "genes": len(genes),
        "biomasses": len(bios),
        "with_gpr": with_gpr,
        "gpr_coverage": with_gpr / max(len(rxns), 1),
        "reaction_ids": {r["id"] for r in rxns},
    }


def _compare(bs: dict, rs: dict, organism: str) -> int:
    """Print side-by-side + parity verdicts. Return 0 if all pass, else 1."""
    print()
    print(f"=== Side-by-side: {organism} ===")
    print(
        f"{'Metric':<22} {'BV-BRC built':>20} {'RAST-job built':>20}"
    )
    print("-" * 64)
    print(f"{'Reactions':<22} {bs['reactions']:>20} {rs['reactions']:>20}")
    print(f"{'Compounds':<22} {bs['compounds']:>20} {rs['compounds']:>20}")
    print(f"{'Genes':<22} {bs['genes']:>20} {rs['genes']:>20}")
    print(f"{'Biomasses':<22} {bs['biomasses']:>20} {rs['biomasses']:>20}")
    print(f"{'Reactions w/ GPR':<22} {bs['with_gpr']:>20} {rs['with_gpr']:>20}")
    print(
        f"{'GPR coverage %':<22} {bs['gpr_coverage']*100:>19.1f}% {rs['gpr_coverage']*100:>19.1f}%"
    )

    shared = bs["reaction_ids"] & rs["reaction_ids"]
    smaller = min(len(bs["reaction_ids"]), len(rs["reaction_ids"]))
    shared_frac = (len(shared) / smaller * 100) if smaller else 0.0
    rxn_diff_pct = (
        abs(rs["reactions"] - bs["reactions"]) / bs["reactions"] * 100
        if bs["reactions"]
        else 0.0
    )
    gpr_diff_pp = abs(rs["gpr_coverage"] - bs["gpr_coverage"]) * 100

    print()
    print("=== Parity verdict ===")
    fails = 0
    for label, value, threshold, op in [
        ("Reaction count delta vs BV-BRC (%)", rxn_diff_pct, 20.0, "<="),
        ("GPR coverage delta (percentage points)", gpr_diff_pp, 10.0, "<="),
        ("Shared reactions / smaller model (%)", shared_frac, 50.0, ">="),
    ]:
        ok = (value <= threshold) if op == "<=" else (value >= threshold)
        mark = "PASS" if ok else "FAIL"
        if not ok:
            fails += 1
        print(f"  [{mark}] {label}: {value:.1f}  (threshold {op} {threshold})")

    biomass_match = bs["biomasses"] == rs["biomasses"]
    if not biomass_match:
        fails += 1
    print(
        f"  [{'PASS' if biomass_match else 'FAIL'}] Biomass count match: "
        f"{bs['biomasses']} == {rs['biomasses']}"
    )

    print(
        f"  [info] Shared reaction set: {len(shared)} reactions "
        f"(BV-BRC unique: {len(bs['reaction_ids'] - rs['reaction_ids'])}; "
        f"RAST unique: {len(rs['reaction_ids'] - bs['reaction_ids'])})"
    )
    return 0 if fails == 0 else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bvbrc-genome", required=True, help="BV-BRC genome ID, e.g. 871585.3")
    ap.add_argument("--rast-job", required=True, help="RAST job ID, e.g. 1670911")
    ap.add_argument("--rast-genome", required=True, help="RAST genome ID, e.g. 871585.30")
    ap.add_argument(
        "--display-name",
        required=True,
        help='Display name for the RAST path, e.g. "Acinetobacter pittii PHEA-2"',
    )
    ap.add_argument(
        "--bvbrc-output-path",
        default=None,
        help="Workspace output path for the BV-BRC model (defaults under ~/modelseed/parity_test/)",
    )
    ap.add_argument(
        "--rast-output-path",
        default=None,
        help="Workspace output path for the RAST model (defaults under ~/modelseed/parity_test/)",
    )
    ap.add_argument(
        "--patric-username",
        default="jplfaria@patricbrc.org",
        help="PATRIC username for default output path computation",
    )
    ap.add_argument(
        "--rast-username",
        default="jplfaria",
        help="RAST username for default output path computation",
    )
    ap.add_argument(
        "--timeout-s",
        type=int,
        default=1500,
        help="Per-job poll timeout in seconds (default 1500 = 25 min)",
    )
    args = ap.parse_args()

    patric_token = os.environ.get("PATRIC_TOKEN") or os.environ.get("MODELSEED_TEST_TOKEN")
    rast_token = os.environ.get("RAST_TOKEN") or os.environ.get("MODELSEED_TEST_RAST_TOKEN")
    if not patric_token:
        sys.exit("PATRIC_TOKEN env var is required")
    if not rast_token:
        sys.exit("RAST_TOKEN env var is required")

    safe_name = args.bvbrc_genome.replace(".", "_")
    bvbrc_path = (
        args.bvbrc_output_path
        or f"/{args.patric_username}/modelseed/parity_test/{safe_name}_bvbrc"
    )
    rast_path = (
        args.rast_output_path
        or f"/{args.rast_username}/modelseed/parity_test/{safe_name}_rast"
    )

    bvbrc_client = _client(patric_token)
    rast_client = _client(rast_token)

    print(f"=== Submitting reconstructs (parallel) ===")
    bvbrc_id = _submit_bvbrc(bvbrc_client, args.bvbrc_genome, bvbrc_path)
    rast_id = _submit_rast(
        rast_client,
        args.display_name,
        args.rast_job,
        args.rast_genome,
        rast_path,
    )
    print(f"  BV-BRC job: {bvbrc_id}")
    print(f"  RAST job:   {rast_id}")
    print(f"  Output paths:")
    print(f"    BV-BRC: {bvbrc_path}")
    print(f"    RAST:   {rast_path}")

    print()
    print("=== Polling BV-BRC job ===")
    bvbrc_rec = _poll_job(bvbrc_client, bvbrc_id, timeout_s=args.timeout_s)
    if bvbrc_rec.get("status") != "completed":
        sys.exit(f"BV-BRC job did not complete: {bvbrc_rec.get('error')}")

    print()
    print("=== Polling RAST job ===")
    rast_rec = _poll_job(rast_client, rast_id, timeout_s=args.timeout_s)
    if rast_rec.get("status") != "completed":
        sys.exit(f"RAST job did not complete: {rast_rec.get('error')}")

    print()
    print("=== Fetching both models ===")
    bvbrc_model = _fetch_model(bvbrc_client, bvbrc_path)
    rast_model = _fetch_model(rast_client, rast_path)

    return _compare(_stats(bvbrc_model), _stats(rast_model), args.display_name)


if __name__ == "__main__":
    raise SystemExit(main())
