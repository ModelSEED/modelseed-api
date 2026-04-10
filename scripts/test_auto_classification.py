#!/usr/bin/env python3
"""E2E test: Auto genome classification via template_type="auto".

Builds models from three reference genomes and verifies the classifier
picks the correct template for each:

  - E. coli K-12 MG1655 (511145.12) → Gram Negative
  - B. subtilis 168 (224308.43) → Gram Positive
  - M. jannaschii DSM 2661 (243232.20) → Archaea

Also verifies explicit template_type override still works.

Usage:
    python scripts/test_auto_classification.py --token TOKEN
    python scripts/test_auto_classification.py --token TOKEN --api-url http://localhost:8000
"""

import argparse
import json
import sys
import time

import requests

DEFAULT_API_URL = "http://poplar.cels.anl.gov:8000"

# Reference genomes for classification testing
GENOMES = {
    "gram_neg": {
        "id": "511145.12",
        "name": "E. coli K-12 MG1655",
        "expected_class": "Gram Negative",
    },
    "gram_pos": {
        "id": "224308.43",
        "name": "B. subtilis 168",
        "expected_class": "Gram Positive",
    },
    "archaea": {
        "id": "243232.20",
        "name": "M. jannaschii DSM 2661",
        "expected_class": "Archaea",
    },
}


def extract_username(token):
    for part in token.split("|"):
        if part.startswith("un="):
            un = part[3:].strip()
            if "@" not in un:
                un = f"{un}@patricbrc.org"
            return un
    return "unknown"


def poll_job(api_url, headers, job_id, max_seconds=600):
    """Poll job until completed/failed. Returns job data dict."""
    for i in range(max_seconds // 5):
        time.sleep(5)
        elapsed = (i + 1) * 5
        try:
            r = requests.get(
                f"{api_url}/api/jobs",
                params={"ids": job_id},
                headers=headers,
                timeout=30,
            )
            if r.status_code != 200:
                continue
            jobs = r.json()
            job = jobs.get(job_id, {})
            status = job.get("status", "")
            if status == "completed":
                print(f"    Job completed in {elapsed}s")
                return job
            if status == "failed":
                error = job.get("result", {}).get("error", "unknown")
                raise RuntimeError(f"Job failed after {elapsed}s: {error}")
            # Show progress
            progress = job.get("progress", {}).get("status", status)
            if elapsed % 30 == 0:
                print(f"    ... {elapsed}s elapsed, status: {progress}")
        except requests.RequestException:
            continue
    raise TimeoutError(f"Job {job_id} timed out after {max_seconds}s")


def submit_reconstruct(api_url, headers, genome_id, template_type="auto", output_path=None):
    """Submit a reconstruct job and return the job ID."""
    body = {
        "genome": genome_id,
        "template_type": template_type,
        "gapfill": False,
    }
    if output_path:
        body["output_path"] = output_path

    r = requests.post(
        f"{api_url}/api/jobs/reconstruct",
        json=body,
        headers={**headers, "Content-Type": "application/json"},
        timeout=30,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Submit failed ({r.status_code}): {r.text[:200]}")

    data = r.json()
    job_id = data.get("id") or data.get("job_id") or data.get("uuid", "")
    if isinstance(data, str):
        job_id = data
    if not job_id:
        # Try extracting from nested result
        for key in ("id", "job_id", "uuid"):
            if key in data:
                job_id = str(data[key])
                break
    if not job_id:
        raise RuntimeError(f"No job ID in response: {data}")
    return job_id


def cleanup_model(api_url, headers, model_ref):
    """Delete a model, ignoring errors."""
    try:
        requests.delete(
            f"{api_url}/api/models",
            params={"ref": model_ref},
            headers=headers,
            timeout=15,
        )
    except Exception:
        pass


def run_tests(api_url, token, skip_archaea=False):
    """Run all classification tests. Returns (passed, failed) counts."""
    headers = {"Authorization": token, "Accept": "application/json"}
    username = extract_username(token)
    passed = 0
    failed = 0

    # ── Health check ──
    print("\n1. Health check...")
    r = requests.get(f"{api_url}/api/health", timeout=10)
    assert r.status_code == 200, f"Health check failed: {r.status_code}"
    print(f"   OK: {r.json()}")

    # ── Test auto classification for each genome ──
    test_cases = list(GENOMES.items())
    if skip_archaea:
        test_cases = [(k, v) for k, v in test_cases if k != "archaea"]

    for label, genome in test_cases:
        genome_id = genome["id"]
        name = genome["name"]
        expected = genome["expected_class"]
        model_ref = f"/{username}/modelseed/auto_test_{label}"

        print(f"\n2. AUTO classification: {name} ({genome_id})")
        print(f"   Expected class: {expected}")
        print(f"   Output path: {model_ref}")

        try:
            # Clean up any leftover from previous test
            cleanup_model(api_url, headers, model_ref)

            # Submit with template_type="auto"
            print("   Submitting reconstruct job (template_type=auto)...")
            job_id = submit_reconstruct(
                api_url, headers, genome_id,
                template_type="auto",
                output_path=model_ref,
            )
            print(f"   Job ID: {job_id}")

            # Poll until done
            job = poll_job(api_url, headers, job_id)
            result = job.get("result", {})
            classification = result.get("classification", "MISSING")

            print(f"   Classification: {classification}")
            print(f"   Reactions: {result.get('reactions', '?')}")
            print(f"   Genes: {result.get('genes', '?')}")

            # Verify classification matches expected
            if classification == expected:
                print(f"   \033[32mPASS\033[0m — {name} correctly classified as {expected}")
                passed += 1
            else:
                print(f"   \033[31mFAIL\033[0m — Expected '{expected}', got '{classification}'")
                failed += 1

            # Verify model was saved and is accessible
            r = requests.get(
                f"{api_url}/api/models/data",
                params={"ref": model_ref},
                headers=headers,
                timeout=30,
            )
            if r.status_code == 200:
                data = r.json()
                n_rxn = len(data.get("reactions", []))
                n_cpd = len(data.get("compounds", []))
                print(f"   Model saved: {n_rxn} reactions, {n_cpd} compounds")
            else:
                print(f"   WARNING: Could not fetch saved model ({r.status_code})")

            # Clean up
            cleanup_model(api_url, headers, model_ref)

        except Exception as e:
            print(f"   \033[31mFAIL\033[0m — {e}")
            failed += 1
            cleanup_model(api_url, headers, model_ref)

    # ── Test explicit override ──
    print(f"\n3. EXPLICIT override: E. coli with template_type='gp' (should use Gram Positive)")
    model_ref = f"/{username}/modelseed/auto_test_override"
    try:
        cleanup_model(api_url, headers, model_ref)

        job_id = submit_reconstruct(
            api_url, headers, "511145.12",
            template_type="gp",
            output_path=model_ref,
        )
        print(f"   Job ID: {job_id}")

        job = poll_job(api_url, headers, job_id)
        result = job.get("result", {})
        template_used = result.get("template_type", "MISSING")

        # When explicit, template_type in result should be "gp"
        # (classification field may still show "gp" or the explicit type)
        if template_used == "gp":
            print(f"   \033[32mPASS\033[0m — Explicit override respected (template_type=gp)")
            passed += 1
        else:
            print(f"   \033[31mFAIL\033[0m — Expected template_type='gp', got '{template_used}'")
            failed += 1

        cleanup_model(api_url, headers, model_ref)

    except Exception as e:
        print(f"   \033[31mFAIL\033[0m — {e}")
        failed += 1
        cleanup_model(api_url, headers, model_ref)

    # ── Summary ──
    total = passed + failed
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("\033[32mAll tests passed!\033[0m")
    else:
        print(f"\033[31m{failed} test(s) failed.\033[0m")
    print(f"{'='*60}")

    return passed, failed


def main():
    parser = argparse.ArgumentParser(
        description="E2E test for auto genome classification"
    )
    parser.add_argument("--token", required=True, help="PATRIC auth token")
    parser.add_argument(
        "--api-url", default=DEFAULT_API_URL,
        help=f"API base URL (default: {DEFAULT_API_URL})"
    )
    parser.add_argument(
        "--skip-archaea", action="store_true",
        help="Skip archaea test (useful if archaea template not deployed yet)"
    )
    args = parser.parse_args()

    print(f"ModelSEED API Auto-Classification E2E Test")
    print(f"API: {args.api_url}")
    print(f"User: {extract_username(args.token)}")

    _, failed = run_tests(args.api_url, args.token, args.skip_archaea)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
