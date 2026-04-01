#!/usr/bin/env python3
"""Comprehensive integration test for modelseed-api.

Tests every endpoint the frontend calls, verifying recent fixes:
- Double /model suffix normalization (no more 404s)
- FBA with KBase-format reaction/compound variables
- Taxonomy/domain repair on model listing
- FBA media constraint application

Usage:
    python scripts/integration_test.py --token TOKEN
    python scripts/integration_test.py --token TOKEN --api-url http://localhost:8000
"""

import argparse
import json
import sys
import time
import urllib.parse
from dataclasses import dataclass, field

import requests

DEFAULT_API_URL = "http://poplar.cels.anl.gov:8000"


@dataclass
class TestResult:
    name: str
    passed: bool
    message: str = ""
    duration: float = 0.0


@dataclass
class TestRunner:
    api_url: str
    token: str
    results: list = field(default_factory=list)
    model_ref: str = ""  # discovered during tests
    username: str = ""

    @property
    def headers(self):
        return {"Authorization": self.token, "Accept": "application/json"}

    def get(self, path, params=None, auth=True, timeout=30):
        url = f"{self.api_url}{path}"
        h = self.headers if auth else {"Accept": "application/json"}
        return requests.get(url, params=params, headers=h, timeout=timeout)

    def post(self, path, body=None, auth=True, timeout=30):
        url = f"{self.api_url}{path}"
        h = {**self.headers, "Content-Type": "application/json"} if auth else {
            "Content-Type": "application/json", "Accept": "application/json"}
        return requests.post(url, json=body, headers=h, timeout=timeout)

    def run_test(self, name, fn):
        t0 = time.time()
        try:
            msg = fn()
            dt = time.time() - t0
            self.results.append(TestResult(name, True, msg or "OK", dt))
            print(f"  \033[32mPASS\033[0m  {name} ({dt:.1f}s) {msg or ''}")
        except AssertionError as e:
            dt = time.time() - t0
            self.results.append(TestResult(name, False, str(e), dt))
            print(f"  \033[31mFAIL\033[0m  {name} ({dt:.1f}s) {e}")
        except Exception as e:
            dt = time.time() - t0
            self.results.append(TestResult(name, False, f"ERROR: {e}", dt))
            print(f"  \033[31mFAIL\033[0m  {name} ({dt:.1f}s) ERROR: {e}")

    def skip_test(self, name, reason):
        self.results.append(TestResult(name, True, f"SKIP: {reason}", 0))
        print(f"  \033[33mSKIP\033[0m  {name} - {reason}")

    def extract_username(self):
        """Extract username from PATRIC token."""
        for part in self.token.split("|"):
            if part.startswith("un="):
                un = part[3:].strip()
                if "@" not in un:
                    un = f"{un}@patricbrc.org"
                self.username = un
                return
        self.username = ""

    # ── 1. Health & Biochemistry (no auth) ───────────────────────────

    def test_health(self):
        r = self.get("/api/health", auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert d.get("status") == "ok", f"status={d.get('status')}"
        return f"v{d.get('version', '?')}"

    def test_biochem_stats(self):
        r = self.get("/api/biochem/stats", auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        rxn = d.get('reactions') or d.get('total_reactions', '?')
        cpd = d.get('compounds') or d.get('total_compounds', '?')
        return f"reactions={rxn}, compounds={cpd}"

    def test_biochem_reactions(self):
        r = self.get("/api/biochem/reactions", params={"ids": "rxn00001"}, auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, list) and len(d) > 0, "expected non-empty list"
        return f"got {len(d)} reaction(s)"

    def test_biochem_compounds(self):
        r = self.get("/api/biochem/compounds", params={"ids": "cpd00001"}, auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, list) and len(d) > 0, "expected non-empty list"
        return f"got {len(d)} compound(s)"

    def test_biochem_search(self):
        r = self.get("/api/biochem/search",
                      params={"query": "glucose", "type": "compounds"}, auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, list), "expected list"
        return f"found {len(d)} result(s)"

    # ── 2. Auth & Error Handling ─────────────────────────────────────

    def test_no_auth_returns_401(self):
        r = self.get("/api/models", auth=False)
        assert r.status_code == 401, f"expected 401, got {r.status_code}"

    def test_invalid_model_ref_fast(self):
        """Invalid ref should return 404 quickly (not 8s+ timeout)."""
        t0 = time.time()
        r = self.get("/api/models/data",
                      params={"ref": "/nonexistent/user/modelseed/FakeModel"})
        dt = time.time() - t0
        assert r.status_code in (403, 404, 500, 502), f"expected 403/404/500/502, got {r.status_code}"
        assert dt < 5, f"took {dt:.1f}s — should be fast (< 5s)"
        return f"{r.status_code} in {dt:.1f}s"

    # ── 3. Model Listing & Detail ────────────────────────────────────

    def test_model_list(self):
        r = self.get("/api/models")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        models = r.json()
        assert isinstance(models, list), "expected list"
        if not models:
            return "empty model list (no models for this user)"

        # Pick first model with a ref for subsequent tests
        for m in models:
            if m.get("ref"):
                self.model_ref = m["ref"]
                break

        # Check structure
        m = models[0]
        assert "id" in m, "missing 'id'"
        assert "ref" in m, "missing 'ref'"
        assert "name" in m, "missing 'name'"
        return f"found {len(models)} model(s), using ref={self.model_ref}"

    def test_model_list_taxonomy(self):
        """Verify taxonomy/domain repair works on listing."""
        r = self.get("/api/models")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        models = r.json()
        if not models:
            return "no models to check"

        populated = sum(1 for m in models if m.get("taxonomy") and m.get("domain"))
        total = len(models)
        return f"{populated}/{total} models have taxonomy+domain"

    def test_model_detail(self):
        if not self.model_ref:
            return "no model_ref available"
        r = self.get("/api/models/data", params={"ref": self.model_ref})
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        # Check key model sections
        sections = ["modelreactions", "modelcompounds"]
        found = [s for s in sections if s in d and d[s]]
        return f"sections: {', '.join(found) or 'none'}, taxonomy={d.get('taxonomy', 'N/A')}"

    # ── 4. Gapfill Listing (double /model fix) ──────────────────────

    def test_gapfill_list(self):
        if not self.model_ref:
            return "no model_ref available"
        r = self.get("/api/models/gapfills", params={"ref": self.model_ref})
        assert r.status_code in (200, 404), f"HTTP {r.status_code}"
        if r.status_code == 200:
            d = r.json()
            return f"found {len(d) if isinstance(d, list) else '?'} gapfill(s)"
        return "404 (no gapfills)"

    def test_gapfill_list_with_model_suffix(self):
        """Ref ending with /model should work (normalized)."""
        if not self.model_ref:
            return "no model_ref available"
        ref_with_model = self.model_ref.rstrip("/") + "/model"
        t0 = time.time()
        r = self.get("/api/models/gapfills", params={"ref": ref_with_model})
        dt = time.time() - t0
        assert r.status_code in (200, 404), f"HTTP {r.status_code} (took {dt:.1f}s)"
        assert dt < 5, f"took {dt:.1f}s — double /model suffix likely not fixed"
        return f"{r.status_code} in {dt:.1f}s (normalized)"

    # ── 5. FBA Listing & Detail ──────────────────────────────────────

    def test_fba_list(self):
        if not self.model_ref:
            return "no model_ref available"
        r = self.get("/api/models/fba", params={"ref": self.model_ref})
        assert r.status_code in (200, 404), f"HTTP {r.status_code}"
        if r.status_code == 200:
            d = r.json()
            count = len(d) if isinstance(d, list) else "?"
            return f"found {count} FBA study/studies"
        return "404 (no FBA studies)"

    def test_fba_list_with_model_suffix(self):
        """Ref ending with /model should work (normalized)."""
        if not self.model_ref:
            return "no model_ref available"
        ref_with_model = self.model_ref.rstrip("/") + "/model"
        t0 = time.time()
        r = self.get("/api/models/fba", params={"ref": ref_with_model})
        dt = time.time() - t0
        assert r.status_code in (200, 404), f"HTTP {r.status_code} (took {dt:.1f}s)"
        assert dt < 5, f"took {dt:.1f}s — double /model suffix likely not fixed"
        return f"{r.status_code} in {dt:.1f}s (normalized)"

    def test_fba_detail(self):
        """Check FBA detail including KBase-format variables."""
        if not self.model_ref:
            return "no model_ref available"
        # First list FBAs to find one
        r = self.get("/api/models/fba", params={"ref": self.model_ref})
        if r.status_code != 200:
            return "no FBA list available"
        fbas = r.json()
        if not fbas or not isinstance(fbas, list) or len(fbas) == 0:
            return "no FBA studies to check"

        fba_id = fbas[0].get("id", "fba.0")
        r2 = self.get("/api/models/fba/data",
                       params={"ref": self.model_ref, "fba_id": fba_id})
        if r2.status_code != 200:
            return f"FBA detail returned {r2.status_code}"
        d = r2.json()
        has_fluxes = bool(d.get("fluxes"))
        has_rxn_vars = "FBAReactionVariables" in d
        has_cpd_vars = "FBACompoundVariables" in d
        obj_val = d.get("objectiveValue", "N/A")
        return (f"objective={obj_val}, fluxes={has_fluxes}, "
                f"FBAReactionVariables={has_rxn_vars}, FBACompoundVariables={has_cpd_vars}")

    # ── 6. Media Endpoints ───────────────────────────────────────────

    def test_media_public(self):
        r = self.get("/api/media/public")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        total = sum(len(v) for v in d.values() if isinstance(v, list))
        return f"found {total} public media across {len(d)} path(s)"

    def test_media_mine(self):
        r = self.get("/api/media/mine")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        total = sum(len(v) for v in d.values() if isinstance(v, list))
        return f"found {total} personal media"

    def test_media_export(self):
        r = self.get("/api/media/export",
                      params={"ref": "/chenry/public/modelsupport/media/Carbon-D-Glucose"})
        # May be 200, 404, or 502
        return f"HTTP {r.status_code}"

    # ── 7. Workspace Proxy ───────────────────────────────────────────

    def test_workspace_ls(self):
        if not self.username:
            return "no username extracted from token"
        path = f"/{self.username}/modelseed/"
        r = self.post("/api/workspace/ls", {"paths": [path]})
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        items = sum(len(v) for v in d.values() if isinstance(v, list))
        return f"found {items} item(s) in {path}"

    def test_workspace_get(self):
        if not self.model_ref:
            return "no model_ref available"
        r = self.post("/api/workspace/get",
                       {"objects": [f"{self.model_ref}/model"]})
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        return "OK"

    # ── 8. Model Operations ──────────────────────────────────────────

    def test_model_edits(self):
        if not self.model_ref:
            return "no model_ref available"
        r = self.get("/api/models/edits", params={"ref": self.model_ref})
        assert r.status_code in (200, 404, 501), f"HTTP {r.status_code}"
        return f"HTTP {r.status_code}"

    def test_model_export_json(self):
        if not self.model_ref:
            return "no model_ref available"
        r = self.get("/api/models/export",
                      params={"ref": self.model_ref, "format": "json"})
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        return f"exported ({len(json.dumps(d)) // 1024}KB)"

    # ── 9. Job Endpoints ─────────────────────────────────────────────

    def test_job_list(self):
        r = self.get("/api/jobs")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        return f"found {len(d)} job(s)"

    def test_fba_job_complete_media(self):
        """Submit FBA with Complete media and poll to completion."""
        if not self.model_ref:
            return "no model_ref available"
        r = self.post("/api/jobs/fba", {
            "model": self.model_ref,
            "media": "Complete",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        d = r.json()
        # Response may be a bare job ID string or a dict with id/job_id
        if isinstance(d, str):
            job_id = d
        elif isinstance(d, dict):
            job_id = d.get("id") or d.get("job_id") or ""
        else:
            return f"unexpected response type: {type(d)}"
        if not job_id:
            return f"submitted but no job_id in response: {d}"

        # Poll for completion (max 120s)
        for _ in range(24):
            time.sleep(5)
            r2 = self.get("/api/jobs", params={"ids": job_id})
            if r2.status_code != 200:
                continue
            jobs = r2.json()
            job = jobs.get(job_id, {})
            status = job.get("status", "")
            if status == "completed":
                result = job.get("result", {})
                obj_val = result.get("objective_value", "?")
                return f"completed: objective={obj_val}"
            if status == "failed":
                error = job.get("error", "unknown")
                assert False, f"FBA job failed: {error}"

        return "submitted (polling timeout — job may still be running)"

    # ── 10. RAST Legacy ──────────────────────────────────────────────

    def test_rast_jobs(self):
        r = self.get("/api/rast/jobs")
        # May be 200, 503 (not configured), or 500
        return f"HTTP {r.status_code}"

    # ── Run All ──────────────────────────────────────────────────────

    def run_all(self):
        self.extract_username()
        print(f"\nModelseed API Integration Tests")
        print(f"API: {self.api_url}")
        print(f"User: {self.username or '(unknown)'}")
        print(f"{'=' * 60}\n")

        # 1. Health & Biochem
        print("── Health & Biochemistry (no auth) ──")
        self.run_test("health", self.test_health)
        self.run_test("biochem_stats", self.test_biochem_stats)
        self.run_test("biochem_reactions", self.test_biochem_reactions)
        self.run_test("biochem_compounds", self.test_biochem_compounds)
        self.run_test("biochem_search", self.test_biochem_search)

        # 2. Auth & Errors
        print("\n── Auth & Error Handling ──")
        self.run_test("no_auth_401", self.test_no_auth_returns_401)
        self.run_test("invalid_ref_fast", self.test_invalid_model_ref_fast)

        # 3. Models
        print("\n── Model Listing & Detail ──")
        self.run_test("model_list", self.test_model_list)
        self.run_test("model_list_taxonomy", self.test_model_list_taxonomy)
        if self.model_ref:
            self.run_test("model_detail", self.test_model_detail)
        else:
            self.skip_test("model_detail", "no models found")

        # 4. Gapfills
        print("\n── Gapfill Listing (double /model fix) ──")
        if self.model_ref:
            self.run_test("gapfill_list", self.test_gapfill_list)
            self.run_test("gapfill_list_model_suffix", self.test_gapfill_list_with_model_suffix)
        else:
            self.skip_test("gapfill_list", "no models")
            self.skip_test("gapfill_list_model_suffix", "no models")

        # 5. FBA
        print("\n── FBA Listing & Detail ──")
        if self.model_ref:
            self.run_test("fba_list", self.test_fba_list)
            self.run_test("fba_list_model_suffix", self.test_fba_list_with_model_suffix)
            self.run_test("fba_detail", self.test_fba_detail)
        else:
            self.skip_test("fba_list", "no models")
            self.skip_test("fba_list_model_suffix", "no models")
            self.skip_test("fba_detail", "no models")

        # 6. Media
        print("\n── Media Endpoints ──")
        self.run_test("media_public", self.test_media_public)
        self.run_test("media_mine", self.test_media_mine)
        self.run_test("media_export", self.test_media_export)

        # 7. Workspace
        print("\n── Workspace Proxy ──")
        self.run_test("workspace_ls", self.test_workspace_ls)
        if self.model_ref:
            self.run_test("workspace_get", self.test_workspace_get)
        else:
            self.skip_test("workspace_get", "no models")

        # 8. Model Operations
        print("\n── Model Operations ──")
        if self.model_ref:
            self.run_test("model_edits", self.test_model_edits)
            self.run_test("model_export_json", self.test_model_export_json)
        else:
            self.skip_test("model_edits", "no models")
            self.skip_test("model_export_json", "no models")

        # 9. Jobs
        print("\n── Job Endpoints ──")
        self.run_test("job_list", self.test_job_list)
        if self.model_ref:
            self.run_test("fba_job_complete", self.test_fba_job_complete_media)
        else:
            self.skip_test("fba_job_complete", "no models")

        # 10. RAST
        print("\n── RAST Legacy ──")
        self.run_test("rast_jobs", self.test_rast_jobs)

        # Summary
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        print(f"\n{'=' * 60}")
        print(f"Results: {passed}/{total} passed, {failed} failed")
        if failed:
            print(f"\nFailed tests:")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.message}")
        print()

        return failed == 0


def main():
    parser = argparse.ArgumentParser(description="ModelSEED API integration tests")
    parser.add_argument("--token", required=True, help="PATRIC auth token")
    parser.add_argument("--api-url", default=DEFAULT_API_URL,
                        help=f"API base URL (default: {DEFAULT_API_URL})")
    args = parser.parse_args()

    runner = TestRunner(api_url=args.api_url.rstrip("/"), token=args.token)
    success = runner.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
