"""Read RAST job annotation data directly from the FIGV-format filesystem.

Replaces the MSSS `getRastGenomeData` JSON-RPC call with direct reads of the
files RAST writes under `<jobs_dir>/<job_id>/rp/<genome_id>/`. The output dict
matches the `RastGenome` shape that `translate_rast_to_kbase_genome` consumes,
so the rest of the pipeline (route handlers, reconstruct task) is unchanged.

The class is safe by construction: only opens files for reading. The mounted
NFS volume is read-only at the kernel level, the docker bind-mount adds `:ro`,
and this module never calls any write syscalls.

File-format reference (per FIGV / SEED toolkit conventions):
- `<job_id>/USER`              one-line user name
- `<job_id>/GENOME`            one-line organism name
- `<job_id>/GENOME_ID`         one-line genome ID
- `<job_id>/PROJECT`           one-line project name
- `<job_id>/TAXONOMY`          one-line semicolon-delimited taxonomy
- `<job_id>/rp/<genome_id>/Features/peg/tbl`            TSV: id, location
- `<job_id>/rp/<genome_id>/Features/peg/fasta`          FASTA: protein sequences
- `<job_id>/rp/<genome_id>/Features/rna/tbl`            TSV: id, location
- `<job_id>/rp/<genome_id>/Features/rna/fasta`          FASTA: rRNA/tRNA sequences (when present)
- `<job_id>/rp/<genome_id>/proposed_functions`          TSV: id, function
- `<job_id>/rp/<genome_id>/contigs`                     FASTA: contig sequences
- `<job_id>/rp/<genome_id>/GENOME`                      one-line organism name
- `<job_id>/rp/<genome_id>/TAXONOMY`                    one-line taxonomy
- `<job_id>/rp/<genome_id>/GENETIC_CODE`                one-line integer (e.g. "11")
"""

from __future__ import annotations

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# Default location of the persistent user-to-job index used by
# `list_jobs_for_user`. Overridable via `index_path` constructor arg.
_DEFAULT_INDEX_PATH = Path("/tmp/rast_user_index.json")

# RAST sharded its job dirs across these volumes on poplar. We try them in
# order until we find the requested job. NFS metadata caches make subsequent
# lookups for the same job sub-millisecond.
_DEFAULT_SHARDS: tuple[str, ...] = (
    "rast-prod-jobs-3",
    "rast-prod-jobs-8",
    "rast-prod-jobs-9",
    "rast-prod-jobs-10",
    "rast-prod-jobs-11",
    "rast-prod-jobs-12",
    "rast-prod-jobs-13",
    "rast-prod-jobs-14",
    "rast-prod-jobs-15",
    "rast-prod-jobs-16",
    "rast-prod-jobs-17",
    "rast-prod-jobs-18",
    "rast-prod-jobs-sto02",
)


class RastFigvReader:
    """Read RAST job annotations from the local FIGV-format filesystem.

    Pass `jobs_dir` pointing at the parent of the per-job directories. On
    poplar that's `/vol/rast-prod/jobs` (a symlink that resolves to one
    shard); the reader will fall back to scanning sibling shards
    (`/vol/rast-prod-jobs-*`) so callers don't have to know which shard
    holds a given job.
    """

    def __init__(self, jobs_dir: str | Path) -> None:
        self.jobs_dir = Path(jobs_dir)
        # The shards live as siblings two levels up: jobs_dir itself is
        # `<vol_root>/rast-prod/jobs` (a symlink) but the actual shards
        # are at `<vol_root>/rast-prod-jobs-<N>/jobs`. So sibling-shard
        # lookup needs to start from `jobs_dir.parent.parent`. Resolve
        # any symlinks first so this works regardless of how the path
        # was passed in.
        try:
            self._vol_root = self.jobs_dir.resolve().parent.parent
        except (OSError, RuntimeError):
            # Fall back to lexical parent.parent when resolve fails (e.g. in
            # tests with non-existent paths).
            self._vol_root = self.jobs_dir.parent.parent
        # Cache job_id to absolute path for the lifetime of the reader to
        # avoid re-scanning shards on every call.
        self._path_cache: dict[str, Path] = {}

    # ---------------------------------------------------------------
    # Public API: per-user job listing
    # ---------------------------------------------------------------

    def list_jobs_for_user(
        self,
        username: str,
        *,
        index_path: str | Path | None = None,
    ) -> list[dict[str, Any]]:
        """Return all RAST jobs owned by `username`, read from disk.

        Backed by a JSON index at `index_path` (or default
        `/tmp/rast_user_index.json`). The index maps job_id to a small
        metadata dict and is built once via `build_user_index()`. Reading
        from the index is sub-millisecond regardless of total job count;
        building it is expensive (~minutes; walks all NFS shards).

        If the index is missing, this raises `FileNotFoundError`. The
        caller is expected to either pre-build the index at startup or
        catch the error and degrade gracefully (e.g. return 503).
        """
        path = Path(index_path) if index_path else _DEFAULT_INDEX_PATH
        if not path.is_file():
            raise FileNotFoundError(
                f"RAST user index not found at {path}; run "
                f"`build_user_index()` to create it."
            )
        with path.open("r") as f:
            index = json.load(f)
        out = []
        for job_id, meta in index.items():
            if meta.get("USER") != username:
                continue
            out.append(
                {
                    "owner": meta.get("USER", ""),
                    "project": meta.get("PROJECT", ""),
                    "id": job_id,
                    "creation_time": meta.get("creation_time", ""),
                    "mod_time": meta.get("mod_time", ""),
                    "genome_size": int(meta.get("genome_size") or 0),
                    "contig_count": int(meta.get("contig_count") or 0),
                    "genome_id": meta.get("GENOME_ID", ""),
                    "genome_name": meta.get("GENOME", ""),
                    "type": "Genome",
                }
            )
        return out

    def build_user_index(
        self,
        *,
        index_path: str | Path | None = None,
        max_workers: int = 13,
        progress_log_every: int = 50000,
    ) -> dict[str, Any]:
        """Walk every shard and build the `job_id to metadata` index.

        Expensive (minutes). Intended to be called once at container
        startup in a background thread, or via an out-of-band cron.
        Writes the index to disk atomically (temp file + rename) so
        readers never see a partial index.

        Returns a small summary dict with timing + counts. The full
        index is left on disk at `index_path`.
        """
        out_path = Path(index_path) if index_path else _DEFAULT_INDEX_PATH
        out_path.parent.mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        all_entries: dict[str, dict[str, Any]] = {}

        def scan_shard(shard_name: str) -> tuple[str, dict[str, dict[str, Any]], int, float]:
            s_start = time.time()
            jobs_root = self._vol_root / shard_name / "jobs"
            if not jobs_root.is_dir():
                return shard_name, {}, 0, 0.0
            shard_index: dict[str, dict[str, Any]] = {}
            n = 0
            with os.scandir(jobs_root) as it:
                for entry in it:
                    n += 1
                    if not entry.is_dir():
                        continue
                    job_id = entry.name
                    job_path = Path(entry.path)
                    user = self._read_text(job_path / "USER")
                    if not user:
                        continue
                    shard_index[job_id] = {
                        "USER": user,
                        "PROJECT": self._read_text(job_path / "PROJECT"),
                        "GENOME": self._read_text(job_path / "GENOME"),
                        "GENOME_ID": self._read_text(job_path / "GENOME_ID"),
                        "shard": shard_name,
                    }
                    if len(shard_index) % progress_log_every == 0:
                        logger.info(
                            "rast_index: %s scanned %d entries (%d users so far) in %.1fs",
                            shard_name, n, len(shard_index), time.time() - s_start,
                        )
            return shard_name, shard_index, n, time.time() - s_start

        with ThreadPoolExecutor(max_workers=max_workers) as exe:
            futures = {exe.submit(scan_shard, s): s for s in _DEFAULT_SHARDS}
            for fut in as_completed(futures):
                shard_name, shard_index, n_dirs, dt = fut.result()
                all_entries.update(shard_index)
                logger.info(
                    "rast_index: shard %s done: %d dirs, %d indexed, %.1fs",
                    shard_name, n_dirs, len(shard_index), dt,
                )

        # Write atomically: tmp file + rename so concurrent readers never
        # see a partial index.
        tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
        with tmp_path.open("w") as f:
            json.dump(all_entries, f, separators=(",", ":"))
        tmp_path.replace(out_path)

        elapsed = time.time() - t0
        summary = {
            "indexed_jobs": len(all_entries),
            "elapsed_seconds": elapsed,
            "index_path": str(out_path),
            "size_bytes": out_path.stat().st_size,
        }
        logger.info("rast_index: build complete: %s", summary)
        return summary

    # ---------------------------------------------------------------
    # Public API: per-job genome data
    # ---------------------------------------------------------------

    def read_rast_genome(self, job_id: str, genome_id: str) -> dict[str, Any]:
        """Assemble a `RastGenome` dict from the on-disk FIGV files.

        Output shape matches MSSS `getRastGenomeData` so it feeds straight
        into `translate_rast_to_kbase_genome` without any adapter.
        """
        if not job_id:
            raise ValueError("job_id is required")
        if not genome_id:
            raise ValueError("genome_id is required")

        job_path = self._resolve_job_path(job_id)
        rp_path = job_path / "rp" / genome_id
        if not rp_path.is_dir():
            raise FileNotFoundError(
                f"RAST genome data not found: {rp_path} (job_id={job_id}, "
                f"genome_id={genome_id})"
            )

        owner = self._read_text(job_path / "USER")
        genome_name = (
            self._read_text(rp_path / "GENOME")
            or self._read_text(job_path / "GENOME")
            or ""
        )
        taxonomy = (
            self._read_text(rp_path / "TAXONOMY")
            or self._read_text(job_path / "TAXONOMY")
            or ""
        )

        contigs = self._parse_contigs_fasta(rp_path / "contigs")
        contig_seqs = [seq for _, seq in contigs]
        size = sum(len(s) for s in contig_seqs)
        gc = self._compute_gc(contig_seqs)

        functions = self._parse_proposed_functions(rp_path / "proposed_functions")

        features: list[dict[str, Any]] = []
        # Iterate every Features/<type> subdirectory present (peg, rna, repeat,
        # and any others RAST writes) so we cover all feature classes MSSS would
        # have returned. Empty/missing dirs are skipped.
        features_root = rp_path / "Features"
        if features_root.is_dir():
            for type_dir in sorted(features_root.iterdir()):
                if not type_dir.is_dir():
                    continue
                type_tag = type_dir.name
                tbl = type_dir / "tbl"
                fasta = type_dir / "fasta"
                if not tbl.is_file():
                    continue
                sequences = self._parse_features_fasta(fasta) if fasta.is_file() else {}
                for fid, location in self._parse_features_tbl(tbl):
                    features.append(
                        self._build_feature_record(
                            fid=fid,
                            location=location,
                            type_tag=type_tag,
                            genome_id=genome_id,
                            job_id=job_id,
                            sequence=sequences.get(fid, ""),
                            function=functions.get(fid, ""),
                        )
                    )

        return {
            "genome": genome_id,
            "name": genome_name,
            # RAST's MSSS uses pipe-delimited; on disk it's semicolon-delimited.
            # Translator handles either, but normalize to pipes for parity with
            # the historical MSSS shape so downstream tests don't drift.
            "taxonomy": taxonomy.replace("; ", "|").replace(";", "|"),
            "source": f"RAST:{job_id}",
            "size": size,
            "gc": gc,
            "DNAsequence": contig_seqs,
            "features": features,
            # Optional fields the translator doesn't read but MSSS returned;
            # keeping them for full shape parity in case other code touches them.
            "owner": owner or "",
            "directory": str(job_path),
        }

    # ---------------------------------------------------------------
    # Path resolution
    # ---------------------------------------------------------------

    def _resolve_job_path(self, job_id: str) -> Path:
        """Find the directory holding this job, scanning shards if needed."""
        cached = self._path_cache.get(job_id)
        if cached and cached.is_dir():
            return cached

        # First try jobs_dir directly (handles the symlinked /vol/rast-prod/jobs case).
        direct = self.jobs_dir / job_id
        if direct.is_dir():
            self._path_cache[job_id] = direct
            return direct

        # Fall back to scanning sibling shards under the /vol root.
        # This handles the case where jobs_dir is the symlinked path but
        # the requested job lives on a different shard than the symlink target.
        for shard_name in _DEFAULT_SHARDS:
            candidate = self._vol_root / shard_name / "jobs" / job_id
            if candidate.is_dir():
                self._path_cache[job_id] = candidate
                return candidate

        raise FileNotFoundError(
            f"RAST job {job_id} not found under {self.jobs_dir} or sibling shards"
        )

    # ---------------------------------------------------------------
    # File parsers
    # ---------------------------------------------------------------

    @staticmethod
    def _read_text(path: Path) -> str:
        """Read a small one-line text file; return stripped content or empty."""
        try:
            with path.open("r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()
        except FileNotFoundError:
            return ""
        except OSError as e:
            logger.warning("Could not read %s: %s", path, e)
            return ""

    @staticmethod
    def _parse_features_tbl(path: Path) -> Iterable[tuple[str, str]]:
        """Parse the SEED `tbl` file: lines are 'fig_id\\tlocation\\t...'."""
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                parts = line.rstrip("\n").split("\t")
                if len(parts) < 2:
                    continue
                fig_id = parts[0].strip()
                location = parts[1].strip()
                if fig_id and location:
                    yield fig_id, location

    @staticmethod
    def _parse_features_fasta(path: Path) -> dict[str, str]:
        """Parse a SEED feature FASTA into a dict mapping fig_id to sequence."""
        return dict(RastFigvReader._iter_fasta(path))

    @staticmethod
    def _parse_contigs_fasta(path: Path) -> list[tuple[str, str]]:
        """Parse the SEED `contigs` FASTA into a list of (contig_id, sequence)."""
        if not path.is_file():
            return []
        return list(RastFigvReader._iter_fasta(path))

    @staticmethod
    def _iter_fasta(path: Path) -> Iterable[tuple[str, str]]:
        """Yield (header_id, sequence) pairs from a FASTA file.

        Header is the first whitespace-delimited token after `>`.
        """
        with path.open("r", encoding="utf-8", errors="replace") as f:
            current_id: str | None = None
            current_seq: list[str] = []
            for line in f:
                line = line.rstrip("\n")
                if line.startswith(">"):
                    if current_id is not None:
                        yield current_id, "".join(current_seq)
                    header = line[1:].strip()
                    current_id = header.split()[0] if header else ""
                    current_seq = []
                else:
                    if current_id is not None:
                        current_seq.append(line.strip())
            if current_id is not None:
                yield current_id, "".join(current_seq)

    @staticmethod
    def _parse_proposed_functions(path: Path) -> dict[str, str]:
        """Parse `proposed_functions` TSV into a dict mapping fig_id to function."""
        out: dict[str, str] = {}
        if not path.is_file():
            return out
        with path.open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                if not line.strip():
                    continue
                parts = line.rstrip("\n").split("\t", 1)
                if len(parts) < 2:
                    continue
                out[parts[0].strip()] = parts[1].strip()
        return out

    # ---------------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _compute_gc(contigs: list[str]) -> float:
        """Compute GC fraction across all contigs. Returns 0.5 if no DNA."""
        gc = 0
        total = 0
        for seq in contigs:
            for ch in seq:
                cl = ch.lower()
                if cl in ("a", "c", "g", "t"):
                    total += 1
                    if cl in ("g", "c"):
                        gc += 1
        if total == 0:
            return 0.5
        return gc / total

    @staticmethod
    def _build_feature_record(
        *,
        fid: str,
        location: str,
        type_tag: str,
        genome_id: str,
        job_id: str,
        sequence: str,
        function: str,
    ) -> dict[str, Any]:
        """Build the per-feature dict with all RAST-style single-element-list values.

        Roles list contains the function string when present, the literal
        "NONE" sentinel otherwise, matching MSSS behavior so the translator's
        existing role-filtering logic continues to apply unchanged.
        """
        try:
            min_loc, max_loc = _parse_location_endpoints(location)
        except ValueError:
            min_loc, max_loc = 0, 0
        direction = "rev" if min_loc > max_loc else "for"
        # MSSS returns LENGTH as `abs(end - start)` (no +1). Match that
        # convention so /api/rast/genome output stays byte-identical
        # with the prior MSSS-wrap implementation.
        length = abs(max_loc - min_loc) if (min_loc or max_loc) else 0

        return {
            "ID": [fid],
            "GENOME": [genome_id],
            "ALIASES": [],
            "TYPE": [type_tag],
            "LOCATION": [location],
            "DIRECTION": [direction],
            "LENGTH": [length],
            "MIN LOCATION": [str(min(min_loc, max_loc)) if (min_loc or max_loc) else ""],
            "MAX LOCATION": [str(max(min_loc, max_loc)) if (min_loc or max_loc) else ""],
            "SOURCE": [f"RAST:{job_id}"],
            "ROLES": [function] if function else ["NONE"],
            "SEQUENCE": [sequence] if sequence else [""],
        }


def _parse_location_endpoints(location: str) -> tuple[int, int]:
    """Parse 'NC_000913.3_337_2799' into (337, 2799).

    Returns (start, end) where start may be > end for reverse-strand features.
    """
    parts = location.rsplit("_", 2)
    if len(parts) != 3:
        raise ValueError(f"unexpected location format: {location!r}")
    try:
        start = int(parts[1])
        end = int(parts[2])
    except ValueError as e:
        raise ValueError(f"non-numeric location coords in {location!r}") from e
    return start, end
