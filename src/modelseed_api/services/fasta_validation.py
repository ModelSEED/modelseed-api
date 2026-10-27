"""Content checks for user-supplied FASTA, run before anything reaches RAST.

Kept dependency-free so the request schema can import it without the
[modeling] extras installed.
"""

from __future__ import annotations

import re
from collections import Counter

# Letters cover nucleotide and amino-acid codes (including IUPAC ambiguity
# codes); '*' is a stop, '-' and '.' are gaps.
_SEQUENCE_LINE = re.compile(r"^[A-Za-z*.\-]+$")
_JUNK_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ufffd]")
# Real uploads sometimes carry a few undecodable characters in free-text
# header descriptions; that is harmless. Binary data is junk throughout.
_BINARY_JUNK_FRACTION = 0.01
_PLAIN_FASTA_HINT = "upload the plain-text FASTA (.fa, .fasta, .fna, .faa)"


def _binary_kind(text: str) -> str | None:
    # A browser that reads a binary upload as text keeps the ASCII bytes and
    # turns the rest into U+FFFD, so the leading magic bytes still identify it.
    if text.startswith("\x1f"):
        return "a gzip-compressed file"
    if text.startswith("PK"):
        return "a zip archive"
    if len(_JUNK_CHARS.findall(text)) > _BINARY_JUNK_FRACTION * len(text):
        return "a binary file"
    return None


def validate_fasta_text(text: str) -> None:
    """Raise ValueError with a user-facing message if `text` is not usable FASTA."""
    # Not a bare lstrip(): Python counts \x1c-\x1f as whitespace, and \x1f is
    # the first gzip magic byte that _binary_kind needs to see.
    text = text.lstrip("\ufeff").lstrip(" \t\r\n")
    if not text:
        raise ValueError("No sequences found in genome_fasta (it is empty)")

    kind = _binary_kind(text)
    if kind:
        action = "Please" if kind == "a binary file" else "Decompress it and"
        raise ValueError(
            f"genome_fasta looks like {kind}, not FASTA text. "
            f"{action} {_PLAIN_FASTA_HINT}."
        )

    if not text.startswith(">"):
        first_line = text.splitlines()[0][:60]
        raise ValueError(
            "genome_fasta must start with a '>' header line (FASTA format); "
            f"got {first_line!r}. Pass FASTA content, not a file path, "
            "workspace reference, or GenBank/EMBL/GFF file."
        )

    ids: list[str] = []
    has_sequence = False
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            header = line[1:].strip()
            ids.append(header.split()[0] if header else "")
            continue
        compact = "".join(line.split())
        if not _SEQUENCE_LINE.match(compact):
            raise ValueError(
                f"genome_fasta line {line_no} is not a valid sequence line: "
                f"{line[:60]!r}. Sequence lines may contain only residue "
                "letters, '*', '-' or '.'."
            )
        has_sequence = True

    if not has_sequence:
        raise ValueError(
            "No sequences found in genome_fasta: it has '>' headers but no "
            "sequence data"
        )

    dupes = sorted(i for i, n in Counter(i for i in ids if i).items() if n > 1)
    if dupes:
        shown = ", ".join(repr(d) for d in dupes[:5])
        more = f" (and {len(dupes) - 5} more)" if len(dupes) > 5 else ""
        raise ValueError(
            f"genome_fasta has duplicate sequence IDs: {shown}{more}. "
            "Each '>' header must start with a unique ID."
        )
