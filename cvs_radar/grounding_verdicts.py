"""Model adjudications for rewrites the character-overlap screen could not clear.

The overlap screen in :mod:`cvs_radar.label_validation` is a cheap first pass, and
on Traditional Chinese it is a noisy one: a good paraphrase routinely swaps in a
synonym that shares no characters with its source (「太貴了」 → 「價格偏高」), so the
screen flags far more honest rewrites than hallucinated ones. Raising or lowering
its threshold trades one error for the other; neither setting can tell a synonym
from an invention, because that judgement is semantic.

So the screen no longer decides. It only selects the small minority of rewrites
worth a second look, and a model adjudicates those. Those verdicts are cached here
by fingerprint exactly like every other model judgement in this project: the
importers stay offline and reproducible, reading a committed CSV rather than
calling a model at import time.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unicodedata
from pathlib import Path

GROUNDING_VERDICTS_PATH = "data/labels/grounding_verdicts.csv"

PROMPT_VERSION = "grounding-v1"

GROUNDED = "grounded"
UNGROUNDED = "ungrounded"
VERDICTS = (GROUNDED, UNGROUNDED)

FIELDNAMES = (
    "fingerprint",
    "rewrite",
    "source_text",
    "verdict",
    "model",
    "prompt_version",
)


def _normalize(text: str) -> str:
    s = unicodedata.normalize("NFKC", str(text or ""))
    s = s.replace("\r", " ").replace("\n", " ").replace("\t", " ")
    return re.sub(r"\s+", " ", s).strip()


def grounding_fingerprint(
    rewrite: str, source_text: str, *, prompt_version: str = PROMPT_VERSION
) -> str:
    """Key a verdict to the exact rewrite/source pair that was judged."""

    payload = "\x1f".join(
        (_normalize(rewrite), _normalize(source_text), str(prompt_version or ""))
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_grounding_verdicts(
    path: str | Path = GROUNDING_VERDICTS_PATH,
) -> dict[str, str]:
    """Return ``{fingerprint: verdict}`` for the current prompt version only."""

    file_path = Path(path)
    if not file_path.exists():
        return {}

    verdicts: dict[str, str] = {}
    with open(file_path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames or any(
            field not in reader.fieldnames for field in FIELDNAMES
        ):
            return {}
        for row in reader:
            fingerprint = str(row.get("fingerprint") or "").strip().lower()
            if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
                continue
            if str(row.get("prompt_version") or "").strip() != PROMPT_VERSION:
                continue
            verdict = str(row.get("verdict") or "").strip()
            if verdict not in VERDICTS:
                continue
            verdicts[fingerprint] = verdict
    return verdicts
