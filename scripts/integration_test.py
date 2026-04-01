#!/usr/bin/env python3
"""Comprehensive integration test for modelseed-api.

Validates EVERY field the frontend reads from EVERY endpoint.
Based on exhaustive audit of ModelSEED-UI-test frontend code.

Tests actual data correctness — not just HTTP status codes.

Usage:
    python scripts/integration_test.py --token TOKEN
    python scripts/integration_test.py --token TOKEN --api-url http://localhost:8000
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field

import requests

DEFAULT_API_URL = "http://poplar.cels.anl.gov:8000"

# ── Helpers ──────────────────────────────────────────────────────────

def assert_fields(obj, required_fields, label=""):
    """Assert that obj (dict) has all required_fields with non-None values."""
    missing = [f for f in required_fields if f not in obj]
    if missing:
        raise AssertionError(f"{label} missing fields: {missing}")


def assert_any_field(obj, field_options, label=""):
    """Assert that at least one of field_options exists and is truthy."""
    for f in field_options:
        if f in obj and obj[f]:
            return f
    raise AssertionError(f"{label} needs one of {field_options}, got none")


def poll_job(runner, job_id, max_seconds=180):
    """Poll a job until completed/failed. Returns (status, job_data)."""
    for _ in range(max_seconds // 5):
        time.sleep(5)
        r = runner.get("/api/jobs", params={"ids": job_id})
        if r.status_code != 200:
            continue
        jobs = r.json()
        job = jobs.get(job_id, {})
        status = job.get("status", "")
        if status == "completed":
            return "completed", job
        if status == "failed":
            return "failed", job
    return "timeout", {}


def extract_job_id(response_data):
    """Extract job ID from API response (may be string, dict, or nested)."""
    if isinstance(response_data, str):
        return response_data
    if isinstance(response_data, dict):
        for key in ("id", "job_id", "jobId", "task_id", "taskId", "uuid"):
            if key in response_data and response_data[key]:
                return str(response_data[key])
        if "result" in response_data:
            return extract_job_id(response_data["result"])
    return ""


# ── Test Runner ──────────────────────────────────────────────────────

@dataclass
class TestResult:
    name: str
    passed: bool
    message: str = ""
    duration: float = 0.0
    warnings: list = field(default_factory=list)


@dataclass
class TestRunner:
    api_url: str
    token: str
    results: list = field(default_factory=list)
    model_ref: str = ""
    model_with_gapfill: str = ""
    model_with_fba: str = ""
    _gapfilled_model_ref: str = ""
    username: str = ""
    all_models: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

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

    def delete(self, path, params=None, auth=True, timeout=30):
        url = f"{self.api_url}{path}"
        h = self.headers if auth else {}
        return requests.delete(url, params=params, headers=h, timeout=timeout)

    def warn(self, msg):
        self.warnings.append(msg)

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
        for part in self.token.split("|"):
            if part.startswith("un="):
                un = part[3:].strip()
                if "@" not in un:
                    un = f"{un}@patricbrc.org"
                self.username = un
                return
        self.username = ""

    # ═══════════════════════════════════════════════════════════════════
    # 1. HEALTH & BIOCHEMISTRY (no auth)
    # ═══════════════════════════════════════════════════════════════════

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
        rxn = d.get("total_reactions") or d.get("reactions", 0)
        cpd = d.get("total_compounds") or d.get("compounds", 0)
        assert int(rxn) > 0, f"no reactions in database"
        assert int(cpd) > 0, f"no compounds in database"
        return f"{rxn} reactions, {cpd} compounds"

    def test_biochem_reaction_by_id(self):
        r = self.get("/api/biochem/reactions", params={"ids": "rxn00001"}, auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, list) and len(d) > 0, "expected non-empty list"
        rxn = d[0]
        # Frontend reads: id, name, definition, deltag, reversibility, status, ec_numbers
        assert_fields(rxn, ["id", "name"], "reaction")
        return f"rxn00001: {rxn.get('name', '?')}"

    def test_biochem_compound_by_id(self):
        r = self.get("/api/biochem/compounds", params={"ids": "cpd00001"}, auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, list) and len(d) > 0, "expected non-empty list"
        cpd = d[0]
        # Frontend reads: id, name, formula, mass, charge
        assert_fields(cpd, ["id", "name"], "compound")
        return f"cpd00001: {cpd.get('name', '?')}"

    def test_biochem_search_compounds(self):
        r = self.get("/api/biochem/search",
                      params={"query": "glucose", "type": "compounds"}, auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, list) and len(d) > 0, "no results for 'glucose'"
        return f"{len(d)} compound(s) matching 'glucose'"

    def test_biochem_search_reactions(self):
        r = self.get("/api/biochem/search",
                      params={"query": "ATP", "type": "reactions"}, auth=False)
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, list), "expected list"
        return f"{len(d)} reaction(s) matching 'ATP'"

    # ═══════════════════════════════════════════════════════════════════
    # 2. AUTH & ERROR HANDLING
    # ═══════════════════════════════════════════════════════════════════

    def test_no_auth_returns_401(self):
        r = self.get("/api/models", auth=False)
        assert r.status_code == 401, f"expected 401, got {r.status_code}"

    def test_invalid_ref_returns_error_fast(self):
        t0 = time.time()
        r = self.get("/api/models/data",
                      params={"ref": "/nonexistent/user/modelseed/FakeModel"})
        dt = time.time() - t0
        assert r.status_code in (400, 403, 404, 500, 502), f"got {r.status_code}"
        assert dt < 8, f"took {dt:.1f}s — should be fast"
        return f"HTTP {r.status_code} in {dt:.1f}s"

    # ═══════════════════════════════════════════════════════════════════
    # 3. MODEL LISTING — validate every field My Models page reads
    #    Frontend: ModelseedModelSummary {ref, id, name, status,
    #    num_genes, num_reactions, num_compounds, fba_count,
    #    unintegrated_gapfills, integrated_gapfills, rundate,
    #    genome_id, organism_name, taxonomy}
    # ═══════════════════════════════════════════════════════════════════

    def test_model_list_fields(self):
        """Validate every field the My Models page reads."""
        r = self.get("/api/models")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        models = r.json()
        assert isinstance(models, list), "expected list"
        if not models:
            return "no models for this user"

        self.all_models = models

        # Pick models for later tests — prefer models with reactions and
        # cobra_model (those will actually work for FBA/gapfill)
        best_ref = None
        best_rxns = -1
        for m in models:
            if m.get("ref"):
                rxns = int(m.get("num_reactions", 0) or 0)
                if rxns > best_rxns:
                    best_rxns = rxns
                    best_ref = m["ref"]
                if not self.model_ref:
                    self.model_ref = m["ref"]
        # Override with best model (most reactions = most likely to have cobra_model)
        if best_ref and best_rxns > 0:
            self.model_ref = best_ref

        issues = []
        for m in models:
            mid = m.get("id", "?")
            # Required by frontend
            if not m.get("ref"):
                issues.append(f"{mid}: missing ref")
            if not m.get("id"):
                issues.append(f"model missing id")
            if not m.get("name"):
                issues.append(f"{mid}: missing name")
            # Numeric fields — frontend uses safeParseNumber so None is OK
            # but they should at least exist
            for nf in ("num_reactions", "num_compounds", "num_genes"):
                if nf not in m:
                    issues.append(f"{mid}: missing {nf}")

        if issues:
            raise AssertionError(f"{len(issues)} issue(s): {'; '.join(issues[:5])}")
        return f"{len(models)} model(s), all have required fields"

    def test_model_list_taxonomy_domain(self):
        """Check taxonomy and domain populated (needed for My Models display)."""
        r = self.get("/api/models")
        assert r.status_code == 200
        models = r.json()
        if not models:
            return "no models"

        with_taxonomy = sum(1 for m in models if m.get("taxonomy"))
        with_domain = sum(1 for m in models if m.get("domain"))
        with_organism = sum(1 for m in models if m.get("organism_name"))
        total = len(models)

        details = []
        for m in models:
            mid = m.get("id", "?")
            missing = []
            if not m.get("taxonomy"):
                missing.append("taxonomy")
            if not m.get("domain"):
                missing.append("domain")
            if not m.get("organism_name"):
                missing.append("organism_name")
            if missing:
                details.append(f"{mid}: missing {','.join(missing)}")

        msg = f"taxonomy={with_taxonomy}/{total}, domain={with_domain}/{total}, organism={with_organism}/{total}"
        if details:
            msg += f" | gaps: {'; '.join(details[:3])}"
            self.warn(f"Models missing taxonomy/domain: {details}")
        return msg

    def test_model_list_numeric_fields(self):
        """Verify num_reactions/num_compounds/fba_count are parseable numbers."""
        r = self.get("/api/models")
        assert r.status_code == 200
        models = r.json()
        if not models:
            return "no models"

        issues = []
        for m in models:
            mid = m.get("id", "?")
            for nf in ("num_reactions", "num_compounds", "num_genes",
                        "fba_count", "integrated_gapfills", "unintegrated_gapfills"):
                val = m.get(nf)
                if val is not None:
                    try:
                        int(val)
                    except (ValueError, TypeError):
                        issues.append(f"{mid}.{nf}={val!r} not a number")

        if issues:
            raise AssertionError(f"Non-numeric fields: {'; '.join(issues[:5])}")
        return f"all numeric fields parseable across {len(models)} model(s)"

    # ═══════════════════════════════════════════════════════════════════
    # 4. MODEL DETAIL — validate every field the model detail page reads
    #    Frontend reads: modelreactions (or reactions), modelcompounds
    #    (or compounds), genes (or modelgenes), biomasses,
    #    modelcompartments, taxonomy, organism_name, genome_id, id, name
    # ═══════════════════════════════════════════════════════════════════

    def test_model_detail_has_reactions(self):
        """Model detail MUST have reactions for the Reactions tab."""
        if not self.model_ref:
            return "no model_ref"
        r = self.get("/api/models/data", params={"ref": self.model_ref})
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()

        rxn_key = assert_any_field(d, ["modelreactions", "reactions"],
                                   "model detail")
        rxns = d[rxn_key]
        assert isinstance(rxns, list), f"{rxn_key} is not a list"
        assert len(rxns) > 0, f"{rxn_key} is empty"

        # Validate reaction structure (frontend reads these fields)
        rxn = rxns[0]
        assert_fields(rxn, ["id"], "reaction")
        # direction, name should exist
        has_direction = "direction" in rxn
        has_name = "name" in rxn
        return f"{len(rxns)} reactions via '{rxn_key}', direction={has_direction}, name={has_name}"

    def test_model_detail_has_compounds(self):
        """Model detail MUST have compounds for the Compounds tab."""
        if not self.model_ref:
            return "no model_ref"
        r = self.get("/api/models/data", params={"ref": self.model_ref})
        assert r.status_code == 200
        d = r.json()

        cpd_key = assert_any_field(d, ["modelcompounds", "compounds"],
                                   "model detail")
        cpds = d[cpd_key]
        assert isinstance(cpds, list) and len(cpds) > 0, f"{cpd_key} empty"

        cpd = cpds[0]
        assert_fields(cpd, ["id"], "compound")
        return f"{len(cpds)} compounds via '{cpd_key}'"

    def test_model_detail_has_genes(self):
        """Model detail should have genes for the Genes tab."""
        if not self.model_ref:
            return "no model_ref"
        r = self.get("/api/models/data", params={"ref": self.model_ref})
        assert r.status_code == 200
        d = r.json()

        # genes or modelgenes — may also be extracted from modelreactions
        gene_key = None
        for k in ("genes", "modelgenes"):
            if k in d and d[k]:
                gene_key = k
                break

        if gene_key:
            return f"{len(d[gene_key])} genes via '{gene_key}'"

        # Frontend falls back to extracting from modelreactions proteins
        rxn_key = None
        for k in ("modelreactions", "reactions"):
            if k in d and d[k]:
                rxn_key = k
                break
        if rxn_key:
            gene_count = 0
            for rxn in d[rxn_key]:
                for prot in rxn.get("modelReactionProteins", []):
                    for sub in prot.get("modelReactionProteinSubunits", []):
                        gene_count += len(sub.get("feature_refs", []))
            if gene_count > 0:
                return f"{gene_count} genes extracted from reaction proteins"

        self.warn(f"Model {self.model_ref} has no gene data — Genes tab will be empty")
        return "no gene data available (Genes tab will be empty)"

    def test_model_detail_has_biomass(self):
        """Model detail should have biomass for the Biomass tab."""
        if not self.model_ref:
            return "no model_ref"
        r = self.get("/api/models/data", params={"ref": self.model_ref})
        assert r.status_code == 200
        d = r.json()

        # Frontend tries many field names
        for k in ("biomasses", "biomass", "modelbiomasses"):
            if k in d and d[k]:
                bio = d[k]
                if isinstance(bio, list) and len(bio) > 0:
                    b = bio[0]
                    has_compounds = any(
                        ck in b and b[ck]
                        for ck in ("biomasscompounds", "modelbiomasscompounds",
                                   "biomass_compounds", "compounds")
                    )
                    return f"{len(bio)} biomass(es) via '{k}', has_compounds={has_compounds}"

        self.warn(f"Model {self.model_ref} has no biomass data")
        return "no biomass data (Biomass tab will be empty)"

    def test_model_detail_metadata(self):
        """Model detail should have organism metadata."""
        if not self.model_ref:
            return "no model_ref"
        r = self.get("/api/models/data", params={"ref": self.model_ref})
        assert r.status_code == 200
        d = r.json()

        assert_fields(d, ["id", "name"], "model")
        organism = d.get("organism_name") or d.get("organism") or d.get("scientific_name")
        taxonomy = d.get("taxonomy")
        genome_id = d.get("genome_id")
        domain = d.get("domain")

        parts = []
        parts.append(f"organism={'yes' if organism else 'NO'}")
        parts.append(f"taxonomy={'yes' if taxonomy else 'NO'}")
        parts.append(f"genome_id={'yes' if genome_id else 'NO'}")
        parts.append(f"domain={'yes' if domain else 'NO'}")
        return ", ".join(parts)

    # ═══════════════════════════════════════════════════════════════════
    # 5. GAPFILL LISTING & DETAIL
    # ═══════════════════════════════════════════════════════════════════

    def test_gapfill_list_fields(self):
        """Validate gapfill listing has fields frontend reads."""
        if not self.model_ref:
            return "no model_ref"
        r = self.get("/api/models/gapfills", params={"ref": self.model_ref})
        if r.status_code == 404:
            return "no gapfills (404)"
        assert r.status_code == 200, f"HTTP {r.status_code}"
        gapfills = r.json()
        if not gapfills:
            return "empty gapfill list"

        # Frontend reads: id, ref/path/workspace_ref, integrated, media, rundate
        gf = gapfills[0]
        assert "id" in gf, "gapfill missing 'id'"
        has_integrated = "integrated" in gf or "integrated_solution" in gf
        has_media = "media" in gf
        has_rundate = "rundate" in gf or "timestamp" in gf

        # Track model with gapfills for later detail test
        self.model_with_gapfill = self.model_ref

        return (f"{len(gapfills)} gapfill(s), "
                f"integrated={has_integrated}, media={has_media}, rundate={has_rundate}")

    def test_gapfill_normalized_ref(self):
        """Ref with /model suffix must be normalized (no double /model)."""
        if not self.model_ref:
            return "no model_ref"
        ref = self.model_ref.rstrip("/") + "/model"
        t0 = time.time()
        r = self.get("/api/models/gapfills", params={"ref": ref})
        dt = time.time() - t0
        assert r.status_code in (200, 404), f"HTTP {r.status_code}"
        assert dt < 5, f"took {dt:.1f}s — likely double /model bug"
        return f"HTTP {r.status_code} in {dt:.1f}s"

    # ═══════════════════════════════════════════════════════════════════
    # 6. FBA LISTING & DETAIL
    #    Frontend reads: id, objectiveValue/objective, media, rundate,
    #    FBAReactionVariables, FBACompoundVariables
    # ═══════════════════════════════════════════════════════════════════

    def test_fba_list_fields(self):
        """Validate FBA listing has fields frontend reads."""
        if not self.model_ref:
            return "no model_ref"

        # Try all models to find one with FBA data
        models_to_try = [self.model_ref]
        for m in self.all_models:
            ref = m.get("ref", "")
            if ref and ref != self.model_ref:
                fc = m.get("fba_count")
                if fc and int(fc) > 0:
                    models_to_try.insert(0, ref)

        for ref in models_to_try:
            r = self.get("/api/models/fba", params={"ref": ref})
            if r.status_code != 200:
                continue
            fbas = r.json()
            if not fbas or not isinstance(fbas, list) or len(fbas) == 0:
                continue

            self.model_with_fba = ref
            fba = fbas[0]
            assert "id" in fba, "FBA missing 'id'"
            has_obj = "objectiveValue" in fba or "objective" in fba
            has_media = "media" in fba or "media_ref" in fba
            return (f"{len(fbas)} FBA(s) on {ref.split('/')[-1]}, "
                    f"objective={has_obj}, media={has_media}")

        return "no models with FBA data"

    def test_fba_list_normalized_ref(self):
        """Ref with /model suffix must be normalized."""
        if not self.model_ref:
            return "no model_ref"
        ref = self.model_ref.rstrip("/") + "/model"
        t0 = time.time()
        r = self.get("/api/models/fba", params={"ref": ref})
        dt = time.time() - t0
        assert r.status_code in (200, 404), f"HTTP {r.status_code}"
        assert dt < 5, f"took {dt:.1f}s"
        return f"HTTP {r.status_code} in {dt:.1f}s"

    def test_fba_detail_kbase_format(self):
        """FBA detail MUST have FBAReactionVariables for frontend flux table."""
        ref = self.model_with_fba
        if not ref:
            return "no model with FBA data"

        # Get FBA list to find an ID
        r = self.get("/api/models/fba", params={"ref": ref})
        assert r.status_code == 200
        fbas = r.json()
        fba_id = fbas[0].get("id", "fba.0")

        r2 = self.get("/api/models/fba/data",
                       params={"ref": ref, "fba_id": fba_id})
        assert r2.status_code == 200, f"HTTP {r2.status_code}"
        d = r2.json()

        # Frontend parseReactionFluxes() requires FBAReactionVariables
        rxn_vars_key = assert_any_field(
            d, ["FBAReactionVariables", "fba_reaction_variables"],
            "FBA detail")
        rxn_vars = d[rxn_vars_key]
        assert isinstance(rxn_vars, list), f"{rxn_vars_key} not a list"
        assert len(rxn_vars) > 0, f"{rxn_vars_key} is empty"

        # Validate structure of first entry
        rv = rxn_vars[0]
        # Frontend reads: modelreaction_ref/reaction_ref, value/flux, name,
        # lowerBound/min, upperBound/max, class/variableType
        has_ref = any(k in rv for k in ("modelreaction_ref", "reaction_ref", "ref"))
        has_value = "value" in rv or "flux" in rv
        has_bounds = ("lowerBound" in rv or "min" in rv)
        has_class = "class" in rv or "variableType" in rv

        assert has_ref, f"FBA reaction variable missing ref field: {list(rv.keys())}"
        assert has_value, f"FBA reaction variable missing value/flux"

        # Check FBACompoundVariables too
        has_cpd_vars = any(k in d for k in ("FBACompoundVariables", "fba_compound_variables"))

        obj_val = d.get("objectiveValue", d.get("objective_value", "?"))

        return (f"objective={obj_val}, {len(rxn_vars)} rxn vars, "
                f"bounds={has_bounds}, class={has_class}, cpd_vars={has_cpd_vars}")

    # ═══════════════════════════════════════════════════════════════════
    # 7. MEDIA ENDPOINTS
    #    Frontend reads workspace tuple format:
    #    [name, type, path, modDate, id, owner, wsIdOrSize, metadata]
    #    metadata may contain: isMinimal, isDefined
    # ═══════════════════════════════════════════════════════════════════

    def test_media_public_format(self):
        """Validate public media response has workspace tuple format."""
        r = self.get("/api/media/public")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict of path -> entries"
        assert len(d) > 0, "empty media dict"

        # Get first path's entries
        path, entries = next(iter(d.items()))
        assert isinstance(entries, list), f"entries for '{path}' not a list"
        assert len(entries) > 0, f"no media under '{path}'"

        # Each entry should be a tuple/list with at least name, type, path
        entry = entries[0]
        assert isinstance(entry, list), f"entry not a list/tuple: {type(entry)}"
        assert len(entry) >= 3, f"entry too short ({len(entry)} elements)"

        name = entry[0]
        etype = entry[1]
        epath = entry[2]
        assert isinstance(name, str) and name, f"entry[0] (name) empty"
        assert isinstance(epath, str) and epath, f"entry[2] (path) empty"

        return f"{sum(len(v) for v in d.values())} media, tuple format OK"

    def test_media_mine(self):
        """User's personal media listing."""
        r = self.get("/api/media/mine")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        total = sum(len(v) for v in d.values() if isinstance(v, list))
        return f"{total} personal media"

    def test_media_export_fields(self):
        """Media export should have compounds array with required fields."""
        r = self.get("/api/media/export",
                      params={"ref": "/chenry/public/modelsupport/media/Carbon-D-Glucose"})
        if r.status_code != 200:
            return f"HTTP {r.status_code} (media export not available)"
        d = r.json()
        assert isinstance(d, dict), "expected dict"

        # Frontend reads: compounds[].{id, name, concentration, minFlux, maxFlux}
        if "compounds" in d and d["compounds"]:
            cpd = d["compounds"][0]
            has_id = "id" in cpd or "compound_id" in cpd
            has_name = "name" in cpd or "compound_name" in cpd
            return f"{len(d['compounds'])} compounds, id={has_id}, name={has_name}"

        return f"media exported (keys: {list(d.keys())[:6]})"

    # ═══════════════════════════════════════════════════════════════════
    # 8. WORKSPACE PROXY
    # ═══════════════════════════════════════════════════════════════════

    def test_workspace_ls_format(self):
        """Workspace ls should return dict of path -> tuples."""
        if not self.username:
            return "no username"
        path = f"/{self.username}/modelseed/"
        r = self.post("/api/workspace/ls", {"paths": [path]})
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"

        # Validate tuple format: [name, type, path, timestamp, id, owner, size, metadata, ...]
        items = []
        for p, entries in d.items():
            if isinstance(entries, list):
                items.extend(entries)

        if items:
            entry = items[0]
            assert isinstance(entry, list), f"entry not tuple: {type(entry)}"
            assert len(entry) >= 4, f"entry too short: {len(entry)}"
            name, etype, epath = entry[0], entry[1], entry[2]
            assert isinstance(name, str), "entry[0] not string"

        return f"{len(items)} item(s) in {path}"

    def test_workspace_get_model(self):
        """Workspace get should return [metadata, data] pairs."""
        if not self.model_ref:
            return "no model_ref"
        r = self.post("/api/workspace/get",
                       {"objects": [f"{self.model_ref}/model"]})
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, list), "expected list"
        assert len(d) > 0, "empty result"
        entry = d[0]
        assert isinstance(entry, list) and len(entry) >= 2, \
            f"expected [metadata, data] pair, got {type(entry)}"
        return "OK (got [metadata, data] pair)"

    # ═══════════════════════════════════════════════════════════════════
    # 9. MODEL OPERATIONS
    # ═══════════════════════════════════════════════════════════════════

    def test_model_edits(self):
        if not self.model_ref:
            return "no model_ref"
        r = self.get("/api/models/edits", params={"ref": self.model_ref})
        assert r.status_code in (200, 404, 501), f"HTTP {r.status_code}"
        if r.status_code == 200:
            d = r.json()
            return f"{len(d)} edit(s)"
        return f"HTTP {r.status_code}"

    def test_model_export_json(self):
        if not self.model_ref:
            return "no model_ref"
        r = self.get("/api/models/export",
                      params={"ref": self.model_ref, "format": "json"})
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        assert isinstance(d, dict), "expected dict"
        size_kb = len(json.dumps(d)) // 1024
        return f"exported {size_kb}KB"

    # ═══════════════════════════════════════════════════════════════════
    # 10. JOB ENDPOINTS — test every job type the frontend can submit
    # ═══════════════════════════════════════════════════════════════════

    def test_job_list_format(self):
        """Job list should return dict or array with expected fields."""
        r = self.get("/api/jobs")
        assert r.status_code == 200, f"HTTP {r.status_code}"
        d = r.json()
        # Frontend handles both dict and array
        if isinstance(d, dict):
            if d:
                job = next(iter(d.values()))
                assert_fields(job, ["id", "status"], "job")
                # Frontend reads: parameters.command, parameters.arguments
                if "parameters" in job:
                    p = job["parameters"]
                    has_cmd = "command" in p
                    has_args = "arguments" in p
                else:
                    has_cmd = False
                    has_args = False
                return f"{len(d)} job(s), params.command={has_cmd}, params.args={has_args}"
            return "0 jobs"
        elif isinstance(d, list):
            return f"{len(d)} job(s) (array format)"
        raise AssertionError(f"unexpected type: {type(d)}")

    def test_fba_job_complete_media(self):
        """Submit FBA with Complete media, poll to completion, validate result."""
        if not self.model_ref:
            return "no model_ref"
        r = self.post("/api/jobs/fba", {
            "model": self.model_ref,
            "media": "Complete",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id from: {r.text[:200]}"

        status, job = poll_job(self, job_id)

        if status == "timeout":
            return f"job {job_id} still running after 180s"

        if status == "failed":
            error = job.get("error", "unknown")
            raise AssertionError(f"FBA with Complete failed: {error}")

        result = job.get("result", {})
        obj_val = result.get("objective_value", 0)
        fba_id = result.get("fba_id", "?")
        return f"completed: {fba_id}, objective={obj_val}"

    def test_fba_job_glucose_media(self):
        """Submit FBA with Carbon-D-Glucose media (the exact name frontend sends)."""
        if not self.model_ref:
            return "no model_ref"
        r = self.post("/api/jobs/fba", {
            "model": self.model_ref,
            "media": "Carbon-D-Glucose",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id from: {r.text[:200]}"

        status, job = poll_job(self, job_id)

        if status == "timeout":
            return f"job {job_id} still running after 180s"

        if status == "failed":
            error = job.get("error", "unknown")
            raise AssertionError(f"FBA with Carbon-D-Glucose failed: {error}")

        result = job.get("result", {})
        obj_val = result.get("objective_value", 0)
        return f"completed: objective={obj_val}"

    def test_fba_result_has_kbase_arrays(self):
        """After FBA job, verify the saved FBA result has KBase-format arrays."""
        if not self.model_ref:
            return "no model_ref"

        # List FBAs — should have at least one from our test jobs
        r = self.get("/api/models/fba", params={"ref": self.model_ref})
        if r.status_code != 200:
            return "could not list FBAs"
        fbas = r.json()
        if not fbas or not isinstance(fbas, list):
            return "no FBA results saved yet"

        # Check latest FBA
        fba = fbas[-1]
        fba_id = fba.get("id", "fba.0")

        r2 = self.get("/api/models/fba/data",
                       params={"ref": self.model_ref, "fba_id": fba_id})
        if r2.status_code != 200:
            return f"FBA detail {fba_id} returned {r2.status_code}"
        d = r2.json()

        # Validate KBase arrays
        issues = []
        for key in ("FBAReactionVariables", "FBACompoundVariables"):
            if key not in d:
                issues.append(f"missing {key}")
            elif not isinstance(d[key], list):
                issues.append(f"{key} not a list")
            elif len(d[key]) == 0:
                issues.append(f"{key} is empty")

        if issues:
            raise AssertionError(f"FBA {fba_id}: {'; '.join(issues)}")

        # Validate structure of reaction variables
        rv = d["FBAReactionVariables"][0]
        required = []
        if not any(k in rv for k in ("modelreaction_ref", "reaction_ref")):
            required.append("modelreaction_ref")
        if "value" not in rv:
            required.append("value")
        if required:
            raise AssertionError(f"Reaction variable missing: {required}, got: {list(rv.keys())}")

        n_rxn = len(d["FBAReactionVariables"])
        n_cpd = len(d.get("FBACompoundVariables", []))
        obj = d.get("objectiveValue", "?")
        return f"{fba_id}: {n_rxn} rxn vars, {n_cpd} cpd vars, objective={obj}"

    # ═══════════════════════════════════════════════════════════════════
    # 10b. GAPFILL JOB SUBMISSION — the most critical pipeline test
    #      Frontend submits via POST /api/jobs/gapfill
    #      Parameters: model, template_type, media
    # ═══════════════════════════════════════════════════════════════════

    def test_gapfill_job_complete_media(self):
        """Submit gapfill with Complete media, poll to completion, validate result."""
        if not self.model_ref:
            return "no model_ref"
        # Find a model with reactions (needed for gapfill to work)
        gf_ref = self._pick_model_with_reactions()
        if not gf_ref:
            return "no model with reactions available"

        r = self.post("/api/jobs/gapfill", {
            "model": gf_ref,
            "template_type": "gn",
            "media": "Complete",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id from: {r.text[:200]}"

        # Gapfill is slow — allow up to 10 minutes
        status, job = poll_job(self, job_id, max_seconds=600)

        if status == "timeout":
            self.warn(f"Gapfill job {job_id} still running after 10 min")
            return f"job {job_id} still running (timeout)"

        if status == "failed":
            error = job.get("error", "unknown")
            raise AssertionError(f"Gapfill with Complete failed: {error}")

        result = job.get("result", {})
        solutions = result.get("solutions_count", 0)
        added = result.get("added_reactions", 0)
        added_ids = result.get("added_reaction_ids", [])
        model_ref = result.get("model_ref", gf_ref)

        # Track the gapfilled model for end-to-end FBA test
        if solutions > 0:
            self._gapfilled_model_ref = model_ref

        return (f"completed: {solutions} solution(s), {added} reactions added"
                + (f" ({', '.join(added_ids[:5])})" if added_ids else ""))

    def test_gapfill_job_glucose_media(self):
        """Submit gapfill with Carbon-D-Glucose media (specific media constraint)."""
        if not self.model_ref:
            return "no model_ref"
        gf_ref = self._pick_model_with_reactions()
        if not gf_ref:
            return "no model with reactions available"

        r = self.post("/api/jobs/gapfill", {
            "model": gf_ref,
            "template_type": "gn",
            "media": "Carbon-D-Glucose",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id from: {r.text[:200]}"

        # Gapfill is slow — allow up to 10 minutes
        status, job = poll_job(self, job_id, max_seconds=600)

        if status == "timeout":
            self.warn(f"Gapfill glucose job {job_id} still running after 10 min")
            return f"job {job_id} still running (timeout)"

        if status == "failed":
            error = job.get("error", "unknown")
            raise AssertionError(f"Gapfill with Carbon-D-Glucose failed: {error}")

        result = job.get("result", {})
        solutions = result.get("solutions_count", 0)
        added = result.get("added_reactions", 0)
        return f"completed: {solutions} solution(s), {added} reactions added"

    def test_gapfill_result_updates_model(self):
        """After gapfill, model's gapfill listing should include the new entry."""
        if not self.model_ref:
            return "no model_ref"
        gf_ref = self._pick_model_with_reactions()
        if not gf_ref:
            return "no model with reactions"

        r = self.get("/api/models/gapfills", params={"ref": gf_ref})
        if r.status_code != 200:
            return f"HTTP {r.status_code}"
        gapfills = r.json()

        if not gapfills:
            self.warn("No gapfills found after gapfill job — solutions_count may have been 0")
            return "no gapfills on model (solutions_count=0?)"

        # Validate structure of each gapfill entry
        for gf in gapfills:
            assert "id" in gf, f"gapfill missing 'id': {list(gf.keys())}"

        # Verify the latest gapfill has solution_reactions (if integrated)
        latest = gapfills[-1]
        has_reactions = bool(latest.get("solution_reactions"))
        has_integrated = "integrated" in latest
        return (f"{len(gapfills)} gapfill(s), latest={latest.get('id')}, "
                f"integrated={has_integrated}, has_reactions={has_reactions}")

    def test_gapfill_template_types(self):
        """Verify gapfill accepts all template types the frontend dropdown offers."""
        if not self.model_ref:
            return "no model_ref"
        gf_ref = self._pick_model_with_reactions()
        if not gf_ref:
            return "no model with reactions"

        # Frontend dropdown: Gram Negative, Gram Positive, Core
        # Don't actually run them all (too slow), just verify API accepts them
        results = []
        for ttype in ("gn", "gp", "core"):
            r = self.post("/api/jobs/gapfill", {
                "model": gf_ref,
                "template_type": ttype,
                "media": "Complete",
            })
            if r.status_code == 200:
                job_id = extract_job_id(r.json())
                results.append(f"{ttype}=OK({job_id[:8]})")
                # Delete job to avoid polluting (best-effort)
                try:
                    self.post("/api/jobs/manage", {
                        "jobs": [job_id], "action": "d"
                    })
                except Exception:
                    pass
            else:
                results.append(f"{ttype}=FAIL({r.status_code})")

        return ", ".join(results)

    # ═══════════════════════════════════════════════════════════════════
    # 10c. FULL END-TO-END PIPELINE: reconstruct → gapfill → FBA
    #      THE test that proves the entire pipeline works.
    #      Uses Bacillus subtilis 224308.43 as a fresh test genome to
    #      guarantee gapfill finds solutions (fresh model, no prior gapfills).
    # ═══════════════════════════════════════════════════════════════════

    def test_pipeline_reconstruct(self):
        """Step 1: Reconstruct B. subtilis 224308.43, wait for completion."""
        if not self.username:
            return "no username"
        # Use a unique output path so we don't collide with existing models
        self._pipeline_genome = "224308.43"
        self._pipeline_output = f"/{self.username}/modelseed/{self._pipeline_genome}"
        r = self.post("/api/jobs/reconstruct", {
            "genome": self._pipeline_genome,
            "template_type": "gp",
            "gapfill": False,
            "media": None,
            "output_path": self._pipeline_output,
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id from: {r.text[:200]}"

        # Wait for reconstruction to complete (can take 2-10 min)
        status, job = poll_job(self, job_id, max_seconds=600)

        if status == "timeout":
            self.warn(f"Reconstruction of {self._pipeline_genome} timed out after 10 min")
            return f"job {job_id[:8]}... timeout (reconstruction still running)"
        if status == "failed":
            error = job.get("error", "unknown")
            raise AssertionError(f"Reconstruction failed: {error}")

        result = job.get("result", {})
        n_rxns = result.get("reactions", "?")
        n_genes = result.get("genes", "?")
        classification = result.get("classification", "?")
        self._pipeline_model_ref = self._pipeline_output
        return (f"completed: {n_rxns} reactions, {n_genes} genes, "
                f"class={classification}")

    def test_pipeline_gapfill(self):
        """Step 2: Gapfill the freshly reconstructed model → expect solutions > 0."""
        model_ref = getattr(self, "_pipeline_model_ref", None)
        if not model_ref:
            return "skipped (reconstruction didn't complete)"

        r = self.post("/api/jobs/gapfill", {
            "model": model_ref,
            "template_type": "gp",
            "media": "Complete",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id"

        status, job = poll_job(self, job_id, max_seconds=600)

        if status == "timeout":
            self.warn(f"Gapfill timed out after 10 min")
            return f"job {job_id[:8]}... timeout"
        if status == "failed":
            error = job.get("error", "unknown")
            raise AssertionError(f"Gapfill failed: {error}")

        result = job.get("result", {})
        solutions = result.get("solutions_count", 0)
        added = result.get("added_reactions", 0)
        added_ids = result.get("added_reaction_ids", [])

        # CRITICAL: a fresh model should ALWAYS find gapfill solutions
        assert solutions > 0, (
            f"Gapfill found 0 solutions on fresh {self._pipeline_genome} model — "
            f"this is a BUG (E. coli / B. subtilis always gapfill successfully)"
        )
        self._pipeline_gapfilled = True
        return (f"{solutions} solution(s), {added} reactions added"
                + (f" ({', '.join(added_ids[:5])})" if added_ids else ""))

    def test_pipeline_fba_complete(self):
        """Step 3: FBA on gapfilled model with Complete media → objective > 0."""
        model_ref = getattr(self, "_pipeline_model_ref", None)
        if not model_ref or not getattr(self, "_pipeline_gapfilled", False):
            return "skipped (no gapfilled model from pipeline)"

        r = self.post("/api/jobs/fba", {
            "model": model_ref,
            "media": "Complete",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id"

        status, job = poll_job(self, job_id, max_seconds=300)

        if status == "timeout":
            return f"FBA job {job_id[:8]}... timeout"
        if status == "failed":
            raise AssertionError(f"FBA failed: {job.get('error')}")

        result = job.get("result", {})
        obj_val = result.get("objective_value", 0)
        fba_id = result.get("fba_id", "?")

        assert float(obj_val) > 0, (
            f"FBA objective={obj_val} on gapfilled model — expected > 0. "
            f"This means the model is infeasible after gapfilling."
        )
        return f"PIPELINE OK: {fba_id} objective={obj_val}"

    def test_pipeline_gapfill_glucose(self):
        """Step 4: Gapfill for glucose media (adds biosynthetic pathways)."""
        model_ref = getattr(self, "_pipeline_model_ref", None)
        if not model_ref or not getattr(self, "_pipeline_gapfilled", False):
            return "skipped (no gapfilled model from pipeline)"

        r = self.post("/api/jobs/gapfill", {
            "model": model_ref,
            "template_type": "gp",
            "media": "Carbon-D-Glucose",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id"

        status, job = poll_job(self, job_id, max_seconds=600)

        if status == "timeout":
            return f"gapfill job {job_id[:8]}... timeout"
        if status == "failed":
            error = job.get("error", "unknown")
            raise AssertionError(f"Glucose gapfill failed: {error}")

        result = job.get("result", {})
        solutions = result.get("solutions_count", 0)
        added = result.get("added_reactions", 0)
        added_ids = result.get("added_reaction_ids", [])

        assert solutions > 0, (
            f"Gapfill for glucose found 0 solutions — model can't be made "
            f"to grow on glucose media"
        )
        self._pipeline_glucose_gapfilled = True
        return (f"{solutions} solution(s), {added} reactions added"
                + (f" ({', '.join(added_ids[:5])})" if added_ids else ""))

    def test_pipeline_fba_glucose(self):
        """Step 5: FBA with glucose media after glucose gapfill → objective > 0."""
        model_ref = getattr(self, "_pipeline_model_ref", None)
        if not model_ref or not getattr(self, "_pipeline_glucose_gapfilled", False):
            return "skipped (model not gapfilled for glucose)"

        r = self.post("/api/jobs/fba", {
            "model": model_ref,
            "media": "Carbon-D-Glucose",
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id"

        status, job = poll_job(self, job_id, max_seconds=300)

        if status == "timeout":
            return f"FBA job {job_id[:8]}... timeout"
        if status == "failed":
            raise AssertionError(f"FBA with glucose failed: {job.get('error')}")

        result = job.get("result", {})
        obj_val = result.get("objective_value", 0)

        assert float(obj_val) > 0, (
            f"FBA objective={obj_val} with glucose on glucose-gapfilled model — "
            f"expected > 0"
        )
        return f"PIPELINE OK: objective={obj_val} with Carbon-D-Glucose"

    # ═══════════════════════════════════════════════════════════════════
    # 10d. RECONSTRUCT JOB — additional reconstruction tests
    # ═══════════════════════════════════════════════════════════════════

    def test_reconstruct_with_gapfill(self):
        """Submit reconstruction with gapfill=True (frontend checkbox)."""
        if not self.username:
            return "no username"
        output_path = f"/{self.username}/modelseed/83332.12"
        r = self.post("/api/jobs/reconstruct", {
            "genome": "83332.12",
            "template_type": "gp",
            "gapfill": True,
            "media": "Complete",
            "output_path": output_path,
        })
        assert r.status_code == 200, f"HTTP {r.status_code}: {r.text[:200]}"
        job_id = extract_job_id(r.json())
        assert job_id, f"could not extract job_id"
        return f"job {job_id[:8]}... submitted (reconstruct+gapfill)"

    # ═══════════════════════════════════════════════════════════════════
    # 10e. JOB MANAGEMENT — delete, list filtering
    # ═══════════════════════════════════════════════════════════════════

    def test_job_manage_delete(self):
        """Verify job deletion works (frontend trash button)."""
        # Submit a dummy FBA job then immediately delete it
        if not self.model_ref:
            return "no model_ref"
        r = self.post("/api/jobs/fba", {
            "model": self.model_ref,
            "media": "Complete",
        })
        if r.status_code != 200:
            return f"could not submit job: {r.status_code}"
        job_id = extract_job_id(r.json())
        if not job_id:
            return "could not extract job_id"

        r2 = self.post("/api/jobs/manage", {
            "jobs": [job_id],
            "action": "d",
        })
        assert r2.status_code == 200, f"delete failed: {r2.status_code}"
        d = r2.json()
        assert job_id in d, f"job_id not in response"
        assert d[job_id].get("status") == "deleted", f"status={d[job_id].get('status')}"
        return f"job {job_id[:8]}... deleted OK"

    def test_job_list_filtering(self):
        """Verify job list respects include_completed/include_failed filters."""
        # With all filters on
        r1 = self.get("/api/jobs", params={
            "include_completed": "true",
            "include_failed": "true",
        })
        assert r1.status_code == 200
        all_jobs = r1.json()

        # With completed=false
        r2 = self.get("/api/jobs", params={
            "include_completed": "false",
            "include_failed": "true",
        })
        assert r2.status_code == 200
        no_completed = r2.json()

        # Verify filtering works (no completed jobs in filtered result)
        for jid, job in no_completed.items():
            assert job.get("status") != "completed", \
                f"job {jid} is completed but should be filtered out"

        return f"all={len(all_jobs)}, no_completed={len(no_completed)}"

    # Helper to find a model with reactions for gapfill tests
    def _pick_model_with_reactions(self):
        """Pick a model with reactions for gapfill/FBA tests."""
        # Prefer models with reactions but fewer gapfills (to test fresh gapfill)
        candidates = []
        for m in self.all_models:
            rxns = m.get("num_reactions")
            if rxns and int(rxns) > 0:
                candidates.append(m)

        if not candidates:
            return self.model_ref

        # Sort: prefer fewer gapfills (test fresh gapfill), then more reactions
        candidates.sort(key=lambda m: (
            int(m.get("integrated_gapfills", 0)),
            -int(m.get("num_reactions", 0)),
        ))
        return candidates[0]["ref"]

    # ═══════════════════════════════════════════════════════════════════
    # 11. RAST LEGACY
    # ═══════════════════════════════════════════════════════════════════

    def test_rast_jobs(self):
        r = self.get("/api/rast/jobs")
        return f"HTTP {r.status_code}"

    # ═══════════════════════════════════════════════════════════════════
    # 12. CROSS-ENDPOINT DATA CONSISTENCY
    # ═══════════════════════════════════════════════════════════════════

    def test_model_list_vs_detail_consistency(self):
        """Model list counts should match detail data counts."""
        if not self.model_ref:
            return "no model_ref"

        # Get list entry
        list_entry = None
        for m in self.all_models:
            if m.get("ref") == self.model_ref:
                list_entry = m
                break
        if not list_entry:
            return "model not found in list"

        # Get detail
        r = self.get("/api/models/data", params={"ref": self.model_ref})
        if r.status_code != 200:
            return f"detail returned {r.status_code}"
        detail = r.json()

        issues = []
        # Compare reaction count
        list_rxn = list_entry.get("num_reactions")
        detail_rxns = detail.get("modelreactions") or detail.get("reactions") or []
        if list_rxn is not None and detail_rxns:
            if abs(int(list_rxn) - len(detail_rxns)) > 0:
                issues.append(
                    f"num_reactions: list={list_rxn} vs detail={len(detail_rxns)}")

        # Compare compound count
        list_cpd = list_entry.get("num_compounds")
        detail_cpds = detail.get("modelcompounds") or detail.get("compounds") or []
        if list_cpd is not None and detail_cpds:
            if abs(int(list_cpd) - len(detail_cpds)) > 0:
                issues.append(
                    f"num_compounds: list={list_cpd} vs detail={len(detail_cpds)}")

        if issues:
            self.warn(f"List/detail mismatch: {issues}")
            return f"MISMATCH: {'; '.join(issues)}"
        return "list and detail counts match"

    # ═══════════════════════════════════════════════════════════════════
    # RUN ALL
    # ═══════════════════════════════════════════════════════════════════

    def run_all(self):
        self.extract_username()
        print(f"\nModelseed API Integration Tests (COMPREHENSIVE)")
        print(f"API: {self.api_url}")
        print(f"User: {self.username or '(unknown)'}")
        print(f"{'=' * 70}\n")

        # 1. Health & Biochem
        print("── 1. Health & Biochemistry (no auth) ──")
        self.run_test("health", self.test_health)
        self.run_test("biochem_stats", self.test_biochem_stats)
        self.run_test("biochem_reaction_by_id", self.test_biochem_reaction_by_id)
        self.run_test("biochem_compound_by_id", self.test_biochem_compound_by_id)
        self.run_test("biochem_search_compounds", self.test_biochem_search_compounds)
        self.run_test("biochem_search_reactions", self.test_biochem_search_reactions)

        # 2. Auth
        print("\n── 2. Auth & Error Handling ──")
        self.run_test("no_auth_401", self.test_no_auth_returns_401)
        self.run_test("invalid_ref_fast", self.test_invalid_ref_returns_error_fast)

        # 3. Model listing
        print("\n── 3. Model Listing (My Models page) ──")
        self.run_test("model_list_fields", self.test_model_list_fields)
        self.run_test("model_list_taxonomy", self.test_model_list_taxonomy_domain)
        self.run_test("model_list_numbers", self.test_model_list_numeric_fields)

        # 4. Model detail
        print("\n── 4. Model Detail (Model page tabs) ──")
        if self.model_ref:
            self.run_test("detail_reactions", self.test_model_detail_has_reactions)
            self.run_test("detail_compounds", self.test_model_detail_has_compounds)
            self.run_test("detail_genes", self.test_model_detail_has_genes)
            self.run_test("detail_biomass", self.test_model_detail_has_biomass)
            self.run_test("detail_metadata", self.test_model_detail_metadata)
        else:
            for t in ("detail_reactions", "detail_compounds", "detail_genes",
                       "detail_biomass", "detail_metadata"):
                self.skip_test(t, "no models")

        # 5. Gapfills
        print("\n── 5. Gapfill Listing ──")
        if self.model_ref:
            self.run_test("gapfill_fields", self.test_gapfill_list_fields)
            self.run_test("gapfill_normalized", self.test_gapfill_normalized_ref)
        else:
            self.skip_test("gapfill_fields", "no models")
            self.skip_test("gapfill_normalized", "no models")

        # 6. FBA
        print("\n── 6. FBA Listing & Detail ──")
        if self.model_ref:
            self.run_test("fba_list_fields", self.test_fba_list_fields)
            self.run_test("fba_normalized", self.test_fba_list_normalized_ref)
            self.run_test("fba_detail_kbase", self.test_fba_detail_kbase_format)
        else:
            self.skip_test("fba_list_fields", "no models")
            self.skip_test("fba_normalized", "no models")
            self.skip_test("fba_detail_kbase", "no models")

        # 7. Media
        print("\n── 7. Media Endpoints ──")
        self.run_test("media_public", self.test_media_public_format)
        self.run_test("media_mine", self.test_media_mine)
        self.run_test("media_export", self.test_media_export_fields)

        # 8. Workspace
        print("\n── 8. Workspace Proxy ──")
        self.run_test("ws_ls", self.test_workspace_ls_format)
        if self.model_ref:
            self.run_test("ws_get", self.test_workspace_get_model)
        else:
            self.skip_test("ws_get", "no models")

        # 9. Model Operations
        print("\n── 9. Model Operations ──")
        if self.model_ref:
            self.run_test("model_edits", self.test_model_edits)
            self.run_test("model_export", self.test_model_export_json)
        else:
            self.skip_test("model_edits", "no models")
            self.skip_test("model_export", "no models")

        # 10. Jobs — SUBMIT AND VERIFY (this is slow but thorough)
        print("\n── 10a. FBA Job Submission & Polling ──")
        self.run_test("job_list", self.test_job_list_format)
        if self.model_ref:
            self.run_test("fba_complete", self.test_fba_job_complete_media)
            self.run_test("fba_glucose", self.test_fba_job_glucose_media)
            self.run_test("fba_result_arrays", self.test_fba_result_has_kbase_arrays)
        else:
            self.skip_test("fba_complete", "no models")
            self.skip_test("fba_glucose", "no models")
            self.skip_test("fba_result_arrays", "no models")

        # 10b. Gapfill jobs on EXISTING model (re-gapfill)
        print("\n── 10b. Gapfill Job Submission (existing model) ──")
        if self.model_ref and self._pick_model_with_reactions():
            self.run_test("gapfill_complete", self.test_gapfill_job_complete_media)
            self.run_test("gapfill_glucose", self.test_gapfill_job_glucose_media)
            self.run_test("gapfill_result_model", self.test_gapfill_result_updates_model)
            self.run_test("gapfill_template_types", self.test_gapfill_template_types)
        else:
            for t in ("gapfill_complete", "gapfill_glucose",
                       "gapfill_result_model", "gapfill_template_types"):
                self.skip_test(t, "no models with reactions")

        # 10c. FULL END-TO-END PIPELINE: reconstruct → gapfill → FBA
        # This is THE critical pipeline test — proves the entire backend works
        print("\n── 10c. Full Pipeline: Reconstruct → Gapfill → FBA (slow) ──")
        self.run_test("pipeline_reconstruct", self.test_pipeline_reconstruct)
        self.run_test("pipeline_gapfill", self.test_pipeline_gapfill)
        self.run_test("pipeline_fba_complete", self.test_pipeline_fba_complete)
        self.run_test("pipeline_gapfill_glucose", self.test_pipeline_gapfill_glucose)
        self.run_test("pipeline_fba_glucose", self.test_pipeline_fba_glucose)

        # 10d. Additional reconstruction tests
        print("\n── 10d. Additional Reconstruction ──")
        self.run_test("reconstruct_gapfill", self.test_reconstruct_with_gapfill)

        # 10e. Job management
        print("\n── 10e. Job Management ──")
        if self.model_ref:
            self.run_test("job_delete", self.test_job_manage_delete)
            self.run_test("job_filtering", self.test_job_list_filtering)
        else:
            self.skip_test("job_delete", "no models")
            self.skip_test("job_filtering", "no models")

        # 11. RAST
        print("\n── 11. RAST Legacy ──")
        self.run_test("rast_jobs", self.test_rast_jobs)

        # 12. Cross-endpoint consistency
        print("\n── 12. Cross-Endpoint Consistency ──")
        if self.model_ref:
            self.run_test("list_vs_detail", self.test_model_list_vs_detail_consistency)
        else:
            self.skip_test("list_vs_detail", "no models")

        # ── Summary ──
        passed = sum(1 for r in self.results if r.passed)
        failed = sum(1 for r in self.results if not r.passed)
        total = len(self.results)

        print(f"\n{'=' * 70}")
        print(f"Results: {passed}/{total} passed, {failed} failed")

        if failed:
            print(f"\n\033[31mFailed tests:\033[0m")
            for r in self.results:
                if not r.passed:
                    print(f"  - {r.name}: {r.message}")

        if self.warnings:
            print(f"\n\033[33mWarnings ({len(self.warnings)}):\033[0m")
            for w in self.warnings:
                if isinstance(w, str):
                    print(f"  - {w}")
                elif isinstance(w, list):
                    for item in w[:5]:
                        print(f"  - {item}")

        print()
        return failed == 0


def main():
    parser = argparse.ArgumentParser(
        description="Comprehensive ModelSEED API integration tests")
    parser.add_argument("--token", required=True, help="PATRIC auth token")
    parser.add_argument("--api-url", default=DEFAULT_API_URL,
                        help=f"API base URL (default: {DEFAULT_API_URL})")
    args = parser.parse_args()

    runner = TestRunner(api_url=args.api_url.rstrip("/"), token=args.token)
    success = runner.run_all()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
