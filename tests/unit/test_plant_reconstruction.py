"""Plant reconstruction: FASTA prep, PlantSEED client parsing, and the
end-to-end workflow against a stub PlantSEED client and local storage.

Fixtures are real PlantSEED output for the first 500 proteins of the
Populus trichocarpa v4.1 proteome (annotate + reconstruct via plantseed:dev
against the Sep09 reference bundle).
"""

from __future__ import annotations

import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from modelseed_api.services import plant_reconstruction as pr
from modelseed_api.services.plantseed_client import (
    PlantSEEDClient,
    PlantSEEDServiceError,
    parse_tool_result,
)

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "un=plantuser|tokenid=x|expiry=9999999999|sig=y"


def _model_fixture() -> dict:
    with gzip.open(FIXTURES / "plantseed_poplar500_model.json.gz", "rt") as fh:
        return json.load(fh)


def _genome_fixture() -> dict:
    return json.loads((FIXTURES / "plantseed_poplar500_annotated_genome.json").read_text())


def _fasta_for(genome: dict) -> str:
    lines = []
    for i, f in enumerate(genome["features"]):
        lines.append(f">Ptrichocarpa_v4.1||{f['id']}.1.p some description")
        lines.append("M" + "ACDEFGHIKLMNPQRSTVWY"[i % 20] * 40 + "*")
    lines.append(">Potri.999G000100.1.p")
    lines.append("MKKKLLLAAA")
    return "\n".join(lines) + "\n"


class TestFastaPrep:
    def test_parse_strips_species_prefix_description_and_stop(self):
        recs = pr.parse_protein_fasta(">Sp||g1.1 desc\nMKV\nLL*\n>g2\nMAA\n>empty\n")
        assert recs == [("g1.1", "MKVLL"), ("g2", "MAA")]

    def test_write_query_fasta_prefixes_species(self, tmp_path):
        out = tmp_path / "q.faa"
        pr.write_query_fasta([("g1", "M" * 100)], "MySpecies_v1", out)
        lines = out.read_text().splitlines()
        assert lines[0] == ">MySpecies_v1||g1"
        assert all(len(line) <= 80 for line in lines[1:])

    @pytest.mark.parametrize("label,expected", [
        ("Populus trichocarpa v4.1", "Populus_trichocarpa_v4.1"),
        ("../evil", "evil"),
        ("///", "plant_genome"),
    ])
    def test_safe_id(self, label, expected):
        assert pr.safe_id(label) == expected


class TestGenomeObject:
    def test_gene_level_annotation_gets_transcript_protein(self):
        proteins = {"Potri.014G034700.2.p": "MBB", "Potri.014G034700.1.p": "MAA"}
        annotated = {"features": [
            {"id": "Potri.014G034700", "functions": ["Role A # plastid", "Role B # cytosol"]},
        ]}
        g = pr.build_genome_object("Ptri", "Populus", annotated, proteins, {"n": 1})
        f = g["features"][0]
        assert f["function"] == "Role A # plastid / Role B # cytosol"
        assert f["protein_translation"] == "MAA"
        assert f["aliases"] == ["Potri.014G034700.1.p"]
        assert g["domain"] == "Plant" and g["source"] == "PlantSEED"

    def test_exact_id_match_has_no_alias(self):
        g = pr.build_genome_object(
            "x", "x", {"features": [{"id": "AT1G01010", "functions": ["R"]}]},
            {"AT1G01010": "MKV"}, {},
        )
        assert "aliases" not in g["features"][0]


class TestToolResultParsing:
    @staticmethod
    def _result(text=None, is_error=False, structured=None):
        content = [SimpleNamespace(type="text", text=text)] if text is not None else []
        return SimpleNamespace(content=content, is_error=is_error,
                               structured_content=structured)

    def test_json_text_payload(self):
        assert parse_tool_result("annotate", self._result('{"genome_path": "/o/g.json"}')) == {
            "genome_path": "/o/g.json"}

    def test_error_payload_raises(self):
        with pytest.raises(PlantSEEDServiceError, match="bundle"):
            parse_tool_result("annotate", self._result('{"error": "bundle failed verify"}'))

    def test_tool_error_raises(self):
        with pytest.raises(PlantSEEDServiceError, match="boom"):
            parse_tool_result("annotate", self._result("boom", is_error=True))

    def test_structured_content_fallback(self):
        r = self._result(structured={"result": {"model_path": "/o/m.json"}})
        assert parse_tool_result("reconstruct", r) == {"model_path": "/o/m.json"}


class TestClientPaths:
    def test_requires_url_and_jobs_dir(self):
        with pytest.raises(PlantSEEDServiceError, match="MCP_URL"):
            PlantSEEDClient(url="", jobs_dir="/x")
        with pytest.raises(PlantSEEDServiceError, match="JOBS_DIR"):
            PlantSEEDClient(url="http://p/mcp", jobs_dir="")

    def test_translates_between_worker_and_server_views(self, tmp_path):
        c = PlantSEEDClient(url="http://p/mcp", jobs_dir=str(tmp_path), server_jobs_dir="/shared")
        assert c.to_server_path(tmp_path / "plant-1" / "q.faa") == "/shared/plant-1/q.faa"
        assert c.to_local_path("/shared/out/mcp/run-1/model.json") == (
            tmp_path / "out" / "mcp" / "run-1" / "model.json")
        with pytest.raises(PlantSEEDServiceError, match="outside the shared directory"):
            c.to_local_path("/output/mcp/run-1/model.json")


class StubPlantSEED(PlantSEEDClient):
    """Plays the plantseed server: reads the query from the shared dir and
    writes the fixture outputs where the real server would."""

    def __init__(self, jobs_dir: Path, annotated: dict | None = None):
        super().__init__(url="http://stub/mcp", jobs_dir=str(jobs_dir),
                         server_jobs_dir="/shared")
        self.annotated = annotated if annotated is not None else _genome_fixture()
        self.calls: list[tuple[str, dict]] = []

    def _write(self, run: str, name: str, obj: dict) -> str:
        d = self.jobs_dir / "out" / "mcp" / run
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_text(json.dumps(obj))
        return f"/shared/out/mcp/{run}/{name}"

    def call_tool(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        if name == "annotate":
            query = self.to_local_path(arguments["genome"]).read_text()
            assert query.startswith(f">{arguments['query_species']}||")
            path = self._write("run-a", "annotated_genome.json", self.annotated)
            return {"genome_path": path, "sha256": "a" * 64,
                    "n_annotated_features": len(self.annotated["features"]),
                    "n_query_genes_searched": 14, "n_query_genes_placed": 14,
                    "status_counts": {"ANNOTATED": len(self.annotated["features"])}}
        if name == "reconstruct":
            path = self._write("run-r", "model.json", _model_fixture())
            return {"model_path": path, "sha256": "b" * 64}
        raise AssertionError(name)


@pytest.fixture
def local_storage(tmp_path, monkeypatch):
    from modelseed_api.config import settings

    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "local_data_dir", str(tmp_path / "ws"))
    (tmp_path / "ws").mkdir()
    from modelseed_api.services.storage_factory import get_storage_service

    return get_storage_service(TOKEN)


def _get(ws, path):
    meta, data = ws.get({"objects": [path]})[0]
    return meta, (json.loads(data) if data else None)


class TestRunPlantReconstruct:
    @pytest.fixture(autouse=True)
    def _needs_cobrakbase(self):
        pytest.importorskip("cobrakbase")

    def test_saves_genome_model_and_cobra_model(self, tmp_path, local_storage):
        jobs = tmp_path / "shared"
        stub = StubPlantSEED(jobs)
        progress: list[str] = []
        genome = _genome_fixture()

        result = pr.run_plant_reconstruct(
            token=TOKEN, genome="Populus trichocarpa", genome_fasta=_fasta_for(genome),
            query_species="Ptrichocarpa_v4.1",
            job_id="job1", progress_cb=progress.append, client=stub,
        )

        out = "/plantuser/plantseed/Populus_trichocarpa"
        assert result["output_path"] == out
        assert result["template_type"] == "plant"
        assert result["reactions"] == len(_model_fixture()["modelreactions"])
        assert [c[0] for c in stub.calls] == ["annotate", "reconstruct"]
        assert "phylum" not in stub.calls[0][1]
        assert stub.calls[0][1]["genome"] == "/shared/plant-job1/query.faa"
        n_proteins = len(genome["features"]) + 1
        assert any(f"Annotating {n_proteins} proteins" in m for m in progress)

        listing = local_storage.ls({"paths": ["/plantuser/plantseed/"]})["/plantuser/plantseed/"]
        folder = next(m for m in listing if m[0] == "Populus_trichocarpa")
        assert folder[1] == "modelfolder"
        assert folder[7]["source"] == "PlantSEED"
        assert folder[7]["plantseed"] == "1"
        assert folder[7]["genome_ref"] == f"{out}/genome"

        _, g = _get(local_storage, f"{out}/genome")
        assert len(g["features"]) == len(genome["features"])
        assert all(f["protein_translation"] for f in g["features"])
        assert g["annotation_summary"]["query_species"] == "Ptrichocarpa_v4.1"

        _, model = _get(local_storage, f"{out}/model")
        assert model["genome_ref"] == f"{out}/genome"
        assert model["id"] == "Populus_trichocarpa"

        raw = local_storage.get({"objects": [f"{out}/cobra_model"]})[0][1]
        cobra_dict = json.loads(raw)
        assert "bio1" in {r["id"] for r in cobra_dict["reactions"]}

        assert not any(p.name.startswith("plant-") for p in jobs.iterdir())
        assert not (jobs / "out" / "mcp" / "run-a").exists()

    def test_cobra_model_grows(self, tmp_path, local_storage):
        """The saved cobra model must carry the default sinks plant biomass
        needs; a bare FBAModelBuilder conversion drops them and grows at 0."""
        import cobra.io

        stub = StubPlantSEED(tmp_path / "shared")
        pr.run_plant_reconstruct(
            token=TOKEN, genome="Ptri", genome_fasta=_fasta_for(_genome_fixture()),
            client=stub,
        )
        raw = local_storage.get({"objects": ["/plantuser/plantseed/Ptri/cobra_model"]})[0][1]
        model = cobra.io.model_from_dict(json.loads(raw))
        model.objective = "bio1"
        assert model.slim_optimize() > 1.0

    def test_nothing_annotated_fails_and_cleans_up(self, tmp_path, local_storage):
        jobs = tmp_path / "shared"
        stub = StubPlantSEED(jobs, annotated={"id": "x", "features": []})
        with pytest.raises(RuntimeError, match="annotated none"):
            pr.run_plant_reconstruct(
                token=TOKEN, genome="x", genome_fasta=">g1\nMKV\n",
                job_id="j2", client=stub,
            )
        assert [c[0] for c in stub.calls] == ["annotate"]
        assert not (jobs / "plant-j2").exists()
        assert local_storage.ls({"paths": ["/plantuser/plantseed/"]})["/plantuser/plantseed/"] == []

    def test_explicit_output_path(self, tmp_path, local_storage):
        stub = StubPlantSEED(tmp_path / "shared")
        r = pr.run_plant_reconstruct(
            token=TOKEN, genome="Ptri", genome_fasta=_fasta_for(_genome_fixture()),
            output_path="/plantuser/modelseed/MyPoplar/", client=stub,
        )
        assert r["output_path"] == "/plantuser/modelseed/MyPoplar"
        assert local_storage.get({"objects": ["/plantuser/modelseed/MyPoplar/genome"]})


def test_job_script_runs_workflow(tmp_path, monkeypatch):
    """plant_reconstruct.py marks the job completed via the shared workflow."""
    import importlib.util

    script = Path(__file__).resolve().parents[2] / "src" / "job_scripts" / "plant_reconstruct.py"
    spec = importlib.util.spec_from_file_location("plant_reconstruct_script", script)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    store = tmp_path / "jobs"
    store.mkdir()
    (store / "j9.json").write_text(json.dumps({"id": "j9", "status": "queued"}))
    seen = {}

    def fake_run(**kwargs):
        seen.update(kwargs)
        kwargs["progress_cb"]("Annotating...")
        return {"status": "success", "genome_id": "g"}

    monkeypatch.setattr(pr, "run_plant_reconstruct", fake_run)
    params = {"genome": "g", "genome_fasta": ">a\nMKV\n", "query_species": "Gx"}
    monkeypatch.setattr("sys.argv", [
        "plant_reconstruct.py", "--job-id", "j9", "--token", TOKEN,
        "--params", json.dumps(params), "--job-store-dir", str(store),
    ])
    assert mod.main() == 0
    job = json.loads((store / "j9.json").read_text())
    assert job["status"] == "completed"
    assert job["result"]["genome_id"] == "g"
    assert seen["query_species"] == "Gx" and seen["job_id"] == "j9"
