"""Layer 5 (load) — Locust scenario for the live API.

Opt-in. Not run in CI. Run quarterly or before announced load.

Usage:
    pip install -e ".[dev,load-tests]"
    export MODELSEED_TEST_TOKEN="<your patric token>"
    export MODELSEED_TEST_API_URL="https://modelseed.org/PMS"  # or staging

    # Headless run, 50 users, 10 min:
    locust -f tests/live/load/locustfile.py \\
        --headless --users 50 --spawn-rate 5 --run-time 10m \\
        --host "$MODELSEED_TEST_API_URL"

    # Or interactive UI on http://localhost:8089:
    locust -f tests/live/load/locustfile.py --host "$MODELSEED_TEST_API_URL"

Pass criteria (per the plan):
- p95 < 2s on biochem reads
- p95 < 8s on model reads
- error rate < 1%

Mix of operations is 70/20/10 (biochem reads / model reads / workspace ls).
"""

from __future__ import annotations

import os
import random

from locust import HttpUser, between, task


# Biochem IDs that are guaranteed to exist (verified by smoke layer).
KNOWN_COMPOUND_IDS = ["cpd00001", "cpd00002", "cpd00027", "cpd00067", "cpd00007"]
KNOWN_REACTION_IDS = ["rxn00001", "rxn00002", "rxn00050", "rxn00100"]
SEARCH_TERMS = ["glucose", "ATP", "phosphate", "pyruvate", "ATPase", "kinase"]


class ReadHeavyUser(HttpUser):
    """A typical browse-mostly user: lots of biochem reads, occasional model
    inspection, occasional workspace listing.

    Token is read from MODELSEED_TEST_TOKEN if set; otherwise the user only
    exercises the no-auth biochem endpoints.
    """

    # Realistic think time between requests.
    wait_time = between(1, 4)

    def on_start(self) -> None:
        token = os.environ.get("MODELSEED_TEST_TOKEN", "").strip()
        if token:
            token = token.removeprefix("Bearer ").strip('"').strip("'")
            self.client.headers["Authorization"] = token
            self._has_auth = True
        else:
            self._has_auth = False

    # ── 70% biochem reads ─────────────────────────────────────────────

    @task(20)
    def get_compound(self) -> None:
        cid = random.choice(KNOWN_COMPOUND_IDS)
        self.client.get(f"/api/biochem/compounds?ids={cid}", name="/api/biochem/compounds")

    @task(20)
    def get_reaction(self) -> None:
        rid = random.choice(KNOWN_REACTION_IDS)
        self.client.get(f"/api/biochem/reactions?ids={rid}", name="/api/biochem/reactions")

    @task(15)
    def search_compounds(self) -> None:
        q = random.choice(SEARCH_TERMS)
        self.client.get(
            f"/api/biochem/search?type=compounds&query={q}&limit=20",
            name="/api/biochem/search?type=compounds",
        )

    @task(10)
    def search_reactions(self) -> None:
        q = random.choice(SEARCH_TERMS)
        self.client.get(
            f"/api/biochem/search?type=reactions&query={q}&limit=20",
            name="/api/biochem/search?type=reactions",
        )

    @task(5)
    def biochem_stats(self) -> None:
        self.client.get("/api/biochem/stats")

    # ── 20% model reads (auth required; skipped if no token) ───────────

    @task(15)
    def list_models(self) -> None:
        if not self._has_auth:
            return
        self.client.get("/api/models", name="/api/models")

    @task(5)
    def list_public_media(self) -> None:
        self.client.get("/api/media/public")

    # ── 10% workspace listing (auth required) ─────────────────────────

    @task(10)
    def workspace_ls(self) -> None:
        if not self._has_auth:
            return
        # Use the bot user's own modelseed dir; if the token's username
        # is not jplfaria@patricbrc.org, this becomes a 200 with empty
        # listing rather than an error.
        username = "jplfaria@patricbrc.org"
        self.client.post(
            "/api/workspace/ls",
            json={"paths": [f"/{username}/modelseed/"]},
            name="/api/workspace/ls",
        )
