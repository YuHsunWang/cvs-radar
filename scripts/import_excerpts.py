#!/usr/bin/env python3
"""Validate and merge model-written excerpt summaries into the fingerprint cache."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.excerpt_labels import (  # noqa: E402
    EXCERPT_LABELS_PATH,
    FIELDNAMES as CACHE_FIELDNAMES,
    PROMPT_VERSION,
    excerpt_fingerprint_v2,
)
from cvs_radar.grounding_verdicts import (  # noqa: E402
    GROUNDING_VERDICTS_PATH,
    load_grounding_verdicts,
)
from cvs_radar.label_validation import (  # noqa: E402
    MAX_REWRITE_LEN,
    GroundingUncertain,
    PendingGrounding,
    RejectedRow,
    enforce_reject_ceiling,
    numbered_candidates,
    parse_source_indices,
    validate_rewrite,
    write_pending_grounding,
    write_rejects,
)

DEFAULT_LABELS_PATH = ROOT / EXCERPT_LABELS_PATH
DEFAULT_REJECTS_PATH = ROOT / "artifacts" / "rejected-excerpts.csv"
DEFAULT_PENDING_PATH = ROOT / "artifacts" / "pending-grounding-excerpts.csv"
SOURCE_FIELDNAMES = (
    "fingerprint",
    "post_id",
    "brand",
    "product_name",
    "other_products",
    "review_text",
    "body_candidates",
    "source_indices",
    "rewrite",
    "model",
    "prompt_version",
)
IMMUTABLE_FIELDS = (
    "fingerprint",
    "post_id",
    "brand",
    "product_name",
    "other_products",
    "review_text",
    "body_candidates",
    "prompt_version",
)


def _read_rows(path: Path, expected_fields: tuple[str, ...]) -> list[dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != expected_fields:
            raise ValueError(
                f"{path}: unexpected columns; expected {','.join(expected_fields)}"
            )
        return list(reader)


def _read_existing(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != CACHE_FIELDNAMES:
            # The prompt-version bump intentionally makes the old v1 cache
            # obsolete. A full current export/import replaces it; no migration is
            # inferred from the old verbatim columns.
            return {}
        return {
            str(row.get("fingerprint") or "").strip().lower(): {
                field: str(row.get(field) or "") for field in CACHE_FIELDNAMES
            }
            for row in reader
            if str(row.get("fingerprint") or "").strip()
        }


def _fingerprint(row: dict[str, str]) -> str:
    fingerprint = str(row.get("fingerprint") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("invalid fingerprint")
    if str(row.get("prompt_version") or "") != PROMPT_VERSION:
        raise ValueError("unexpected prompt_version")
    candidates = numbered_candidates(row.get("body_candidates"), field="body_candidates")
    recomputed = excerpt_fingerprint_v2(
        row.get("post_id") or "",
        row.get("product_name") or "",
        row.get("review_text") or "",
        brand=row.get("brand") or "",
        other_products=row.get("other_products") or "",
        candidate_sentences=candidates,
        prompt_version=row.get("prompt_version") or "",
    )
    if fingerprint != recomputed:
        raise ValueError("fingerprint does not match immutable inputs")
    return fingerprint


def _validate_structure(
    source_rows: list[dict[str, str]], labeled_rows: list[dict[str, str]]
) -> None:
    if len(labeled_rows) != len(source_rows):
        raise ValueError(
            f"labeled file row count {len(labeled_rows)} does not match source {len(source_rows)}"
        )
    source_fingerprints = [_fingerprint(row) for row in source_rows]
    if len(set(source_fingerprints)) != len(source_fingerprints):
        raise ValueError("source contains duplicate fingerprints")
    labeled_fingerprints: list[str] = []
    for line_number, (source, labeled) in enumerate(
        zip(source_rows, labeled_rows, strict=True), start=2
    ):
        fingerprint = _fingerprint(labeled)
        labeled_fingerprints.append(fingerprint)
        if fingerprint != source_fingerprints[line_number - 2]:
            raise ValueError(f"row {line_number}: fingerprint/order changed")
        for field in IMMUTABLE_FIELDS:
            if labeled.get(field, "") != source.get(field, ""):
                raise ValueError(f"row {line_number}: immutable field {field} changed")
    if len(set(labeled_fingerprints)) != len(labeled_fingerprints):
        raise ValueError("labeled file contains duplicate fingerprints")


def _validate_row(
    row: dict[str, str],
    line_number: int,
    verdicts: dict[str, str] | None = None,
) -> tuple[str, tuple[int, ...], str, list[PendingGrounding]]:
    fingerprint = str(row.get("fingerprint") or "")
    source_texts = numbered_candidates(row.get("body_candidates"), field="body_candidates")
    try:
        source_indices = parse_source_indices(row.get("source_indices"), field="source_indices")
    except ValueError as exc:
        raise ValueError(f"row {line_number}: {exc}") from exc
    rewrite = str(row.get("rewrite") or "")
    pending: list[PendingGrounding] = []
    try:
        validate_rewrite(
            rewrite,
            source_texts=source_texts,
            source_indices=source_indices,
            other_products=row.get("other_products") or "",
            field=f"row {line_number}: rewrite",
            verdicts=verdicts,
        )
    except GroundingUncertain as exc:
        pending.append(
            PendingGrounding(
                line_number=line_number,
                fingerprint=fingerprint,
                field="rewrite",
                rewrite=exc.rewrite,
                source_text=exc.source_text,
                product_name=str(row.get("product_name") or ""),
            )
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    mutable = (row.get("source_indices") or "", rewrite)
    model = str(row.get("model") or "").strip()
    if any(mutable) and not model:
        raise ValueError(f"row {line_number}: model is required for a completed row")
    if len(rewrite) > MAX_REWRITE_LEN:
        raise ValueError(f"row {line_number}: rewrite longer than {MAX_REWRITE_LEN}")
    return fingerprint, source_indices, rewrite, pending


def import_labels(
    labeled_path: Path,
    source_path: Path,
    labels_path: Path = DEFAULT_LABELS_PATH,
    *,
    replace: bool = False,
    model_tag: str = "",
    rejects_path: Path | None = None,
    pending_path: Path | None = None,
    verdicts_path: Path | None = None,
) -> tuple[int, int, int, int, int]:
    """Return ``(added, replaced, skipped, rejected, held)``.

    Structural problems (row count, fingerprints, ordering, immutable columns) still
    refuse the whole file: they mean the file itself is wrong. A row that is
    definitely wrong is quarantined, and too many of those refuse everything again.
    A row the overlap screen merely could not clear is *held* for adjudication —
    see :func:`cvs_radar.label_validation.validate_rewrite` for why that third
    outcome exists.
    """

    # Resolved here, not as default arguments: defaults bound at def time
    # cannot be redirected, and tests must never write into the repo.
    rejects_path = rejects_path or DEFAULT_REJECTS_PATH
    pending_path = pending_path or DEFAULT_PENDING_PATH
    verdicts_path = verdicts_path or ROOT / GROUNDING_VERDICTS_PATH

    source_rows = _read_rows(source_path, SOURCE_FIELDNAMES)
    labeled_rows = _read_rows(labeled_path, SOURCE_FIELDNAMES)
    _validate_structure(source_rows, labeled_rows)

    verdicts = load_grounding_verdicts(verdicts_path)
    existing = _read_existing(labels_path)
    added = replaced = skipped = 0
    rejected: list[RejectedRow] = []
    pending: list[PendingGrounding] = []
    held = 0
    considered = 0
    accepted_rows: list[tuple[str, tuple[int, ...], str, dict[str, str]]] = []
    for line_number, row in enumerate(labeled_rows, start=2):
        try:
            fingerprint, source_indices, rewrite, row_pending = _validate_row(
                row, line_number, verdicts
            )
        except ValueError as exc:
            considered += 1
            rejected.append(
                RejectedRow(
                    line_number=line_number,
                    fingerprint=str(row.get("fingerprint") or ""),
                    reason=str(exc),
                    row=row,
                )
            )
            continue
        if any((row.get("source_indices") or "", rewrite)):
            considered += 1
        if row_pending:
            pending.extend(row_pending)
            held += 1
            continue
        accepted_rows.append((fingerprint, source_indices, rewrite, row))

    enforce_reject_ceiling(rejected, considered)
    if rejected:
        write_rejects(rejects_path, rejected, SOURCE_FIELDNAMES)
    if pending:
        write_pending_grounding(pending_path, pending)
    elif pending_path.exists():
        # A stale queue would make the ops runner adjudicate the same rows
        # forever; an empty queue means there is nothing left to judge.
        pending_path.unlink()

    for fingerprint, source_indices, rewrite, row in accepted_rows:
        model = str(row.get("model") or "").strip()
        if not source_indices and not rewrite and not model:
            skipped += 1
            continue
        output = {
            "fingerprint": fingerprint,
            "post_id": str(row.get("post_id") or ""),
            "brand": str(row.get("brand") or ""),
            "product_name": str(row.get("product_name") or ""),
            "source_indices": str(row.get("source_indices") or ""),
            "rewrite": rewrite,
            "model": model_tag or model or "subscription-llm",
            "prompt_version": str(row.get("prompt_version") or ""),
        }
        if fingerprint in existing:
            if not replace:
                continue
            existing[fingerprint] = output
            replaced += 1
        else:
            existing[fingerprint] = output
            added += 1

    labels_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = labels_path.with_suffix(labels_path.suffix + ".tmp")
    with open(temporary, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CACHE_FIELDNAMES)
        writer.writeheader()
        writer.writerows(existing[key] for key in sorted(existing))
    temporary.replace(labels_path)
    return added, replaced, skipped, len(rejected), held


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("labeled", type=Path)
    parser.add_argument("--source", type=Path, required=True, help="original exported CSV")
    parser.add_argument("--labels", type=Path, default=DEFAULT_LABELS_PATH)
    parser.add_argument("--rejects", type=Path, default=DEFAULT_REJECTS_PATH)
    parser.add_argument("--pending", type=Path, default=DEFAULT_PENDING_PATH)
    parser.add_argument("--model-tag", default="")
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    added, replaced, skipped, rejected, held = import_labels(
        args.labeled,
        args.source,
        args.labels,
        replace=args.replace,
        model_tag=args.model_tag,
        rejects_path=args.rejects,
        pending_path=args.pending,
    )
    notes = []
    if rejected:
        notes.append(f"{rejected} quarantined -> {args.rejects}")
    if held:
        notes.append(f"{held} awaiting grounding verdicts -> {args.pending}")
    suffix = f"; {'; '.join(notes)}" if notes else ""
    print(
        f"imported excerpts: {added} added, {replaced} replaced, "
        f"{skipped} skipped, {rejected} rejected, {held} held{suffix}"
    )


if __name__ == "__main__":
    main()
