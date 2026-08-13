#!/usr/bin/env python3
"""Validate and merge model-written representative-comment rewrites."""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.comment_labels import (  # noqa: E402
    COMMENT_PICKS_PATH,
    FIELDNAMES as CACHE_FIELDNAMES,
    PROMPT_VERSION,
)
from cvs_radar.grounding_verdicts import (  # noqa: E402
    GROUNDING_VERDICTS_PATH,
    load_grounding_verdicts,
)
from cvs_radar.label_validation import (  # noqa: E402
    GroundingUncertain,
    PendingGrounding,
    RejectedRow,
    enforce_reject_ceiling,
    numbered_candidates,
    parse_rewrites,
    validate_rewrite,
    write_pending_grounding,
    write_rejects,
)

DEFAULT_LABELS_PATH = ROOT / COMMENT_PICKS_PATH
DEFAULT_REJECTS_PATH = ROOT / "artifacts" / "rejected-comment-picks.csv"
DEFAULT_PENDING_PATH = ROOT / "artifacts" / "pending-grounding-comment-picks.csv"
SOURCE_FIELDNAMES = (
    "fingerprint",
    "brand",
    "product_name",
    "other_products",
    "comments",
    "body_candidates",
    "positive_rewrites",
    "negative_rewrites",
    "positive_body_rewrites",
    "negative_body_rewrites",
    "model",
    "prompt_version",
)
IMMUTABLE_FIELDS = (
    "fingerprint",
    "brand",
    "product_name",
    "other_products",
    "comments",
    "body_candidates",
    "prompt_version",
)
REWRITE_FIELDS = (
    "positive_rewrites",
    "negative_rewrites",
    "positive_body_rewrites",
    "negative_body_rewrites",
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
            # Old v1 index-only rows are intentionally not migrated. The current
            # full delta import replaces them with current-prompt rewrites.
            return {}
        return {
            str(row.get("fingerprint") or "").strip().lower(): {
                field: str(row.get(field) or "") for field in CACHE_FIELDNAMES
            }
            for row in reader
            if str(row.get("fingerprint") or "").strip()
        }


def _fingerprint(row: dict[str, str]) -> str:
    from cvs_radar.comment_labels import comment_picks_fingerprint_v2

    fingerprint = str(row.get("fingerprint") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("invalid fingerprint")
    if str(row.get("prompt_version") or "") != PROMPT_VERSION:
        raise ValueError("unexpected prompt_version")
    comments = numbered_candidates(row.get("comments"), field="comments")
    body = numbered_candidates(row.get("body_candidates"), field="body_candidates")
    recomputed = comment_picks_fingerprint_v2(
        row.get("brand") or "",
        row.get("product_name") or "",
        comments,
        body,
        other_products=row.get("other_products") or "",
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
) -> tuple[str, list[PendingGrounding]]:
    comments = numbered_candidates(row.get("comments"), field="comments")
    body = numbered_candidates(row.get("body_candidates"), field="body_candidates")
    parsed: dict[str, tuple] = {}
    for field in REWRITE_FIELDS:
        try:
            parsed[field] = parse_rewrites(row.get(field), field=field)
        except ValueError as exc:
            raise ValueError(f"row {line_number}: {exc}") from exc

    pending: list[PendingGrounding] = []
    for field, rewrites in parsed.items():
        source_texts = comments if field in {"positive_rewrites", "negative_rewrites"} else body
        for item_index, item in enumerate(rewrites):
            try:
                validate_rewrite(
                    item.text,
                    source_texts=source_texts,
                    source_indices=(item.source_index,),
                    other_products=row.get("other_products") or "",
                    field=f"row {line_number}: {field}[{item_index}]",
                    verdicts=verdicts,
                )
            except GroundingUncertain as exc:
                pending.append(
                    PendingGrounding(
                        line_number=line_number,
                        fingerprint=str(row.get("fingerprint") or ""),
                        field=field,
                        rewrite=exc.rewrite,
                        source_text=exc.source_text,
                        product_name=str(row.get("product_name") or ""),
                    )
                )
            except ValueError as exc:
                raise ValueError(str(exc)) from exc

    comment_overlap = {
        item.source_index for item in parsed["positive_rewrites"]
    } & {item.source_index for item in parsed["negative_rewrites"]}
    if comment_overlap:
        raise ValueError(
            f"row {line_number}: comment source index appears in both polarities"
        )
    body_overlap = {
        item.source_index for item in parsed["positive_body_rewrites"]
    } & {item.source_index for item in parsed["negative_body_rewrites"]}
    if body_overlap:
        raise ValueError(
            f"row {line_number}: body source index appears in both polarities"
        )

    model = str(row.get("model") or "").strip()
    if any(str(row.get(field) or "").strip() for field in REWRITE_FIELDS) and not model:
        raise ValueError(f"row {line_number}: model is required for a completed row")
    fingerprint = str(row.get("fingerprint") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError(f"row {line_number}: invalid fingerprint")
    return fingerprint, pending


def import_picks(
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

    Three outcomes, not two. Structural problems still refuse the whole file. A row
    whose content is definitely wrong — a cross-product rewrite, a bad index, a
    model-confirmed hallucination — is quarantined, and too many of those still
    refuse everything. A row whose only problem is that the overlap screen could not
    clear it is *held*: not imported, not rejected, just queued for adjudication in
    ``pending_path`` until ``scripts/verify_grounding.sh`` records a verdict.

    Nothing is ever repaired in any of the three paths.
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
    accepted_rows: list[tuple[str, dict[str, str]]] = []
    for line_number, row in enumerate(labeled_rows, start=2):
        has_content = any(
            str(row.get(field) or "").strip() for field in REWRITE_FIELDS
        )
        try:
            fingerprint, row_pending = _validate_row(row, line_number, verdicts)
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
        if has_content:
            considered += 1
        if row_pending:
            # Held, not rejected: the row's own rewrites may be perfectly faithful.
            # Importing it now would cache an unadjudicated rewrite; rejecting it
            # would throw away a likely-good one. Queue it and move on.
            pending.extend(row_pending)
            held += 1
            continue
        accepted_rows.append((fingerprint, row))

    enforce_reject_ceiling(rejected, considered)
    if rejected:
        write_rejects(rejects_path, rejected, SOURCE_FIELDNAMES)
    if pending:
        write_pending_grounding(pending_path, pending)
    elif pending_path.exists():
        # A stale queue would make the ops runner adjudicate the same rows
        # forever; an empty queue means there is nothing left to judge.
        pending_path.unlink()

    for fingerprint, row in accepted_rows:
        model = str(row.get("model") or "").strip()
        if not any(str(row.get(field) or "").strip() for field in REWRITE_FIELDS) and not model:
            skipped += 1
            continue
        output = {
            "fingerprint": fingerprint,
            "brand": str(row.get("brand") or ""),
            "product_name": str(row.get("product_name") or ""),
            **{field: str(row.get(field) or "") for field in REWRITE_FIELDS},
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

    added, replaced, skipped, rejected, held = import_picks(
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
        f"imported comment rewrites: {added} added, {replaced} replaced, "
        f"{skipped} skipped, {rejected} rejected, {held} held{suffix}"
    )


if __name__ == "__main__":
    main()
