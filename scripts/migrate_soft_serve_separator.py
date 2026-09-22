#!/usr/bin/env python3
"""Re-key label caches after preserving the x in soft-serve swirl names.

The migration reconstructs both sides from data/posts.jsonl.  It changes cached
judgements only when a product-name label differs from the corrected rule guess
solely by the missing separator; every other cache change is a key/context rename.
"""

from __future__ import annotations

import argparse
import copy
import csv
import json
import sys
import unicodedata
from collections import defaultdict
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cvs_radar.comment_labels import (  # noqa: E402
    comment_picks_fingerprint_v2,
    other_products_for_group,
)
from cvs_radar.excerpt_labels import (  # noqa: E402
    excerpt_fingerprint_v2,
    format_other_products,
)
from cvs_radar.product_categories import product_category_fingerprint  # noqa: E402
from cvs_radar.product_labels import (  # noqa: E402
    format_rule_guess,
    product_name_fingerprint,
    product_name_fingerprint_v2,
)
from cvs_radar.scoring import (  # noqa: E402
    _body_candidates,
    _rep_candidates,
    group_products,
    preprocess_posts,
    representative_product_name,
)
from cvs_radar.scoring import identity  # noqa: E402
from cvs_radar.sentiment import comment_fingerprint_v2  # noqa: E402
from cvs_radar.store import load_posts  # noqa: E402

CACHE_PATHS = {
    "product_name": ROOT / "data/labels/product_name_labels.csv",
    "excerpt": ROOT / "data/labels/excerpt_labels.csv",
    "comment_picks": ROOT / "data/labels/comment_picks.csv",
    "category": ROOT / "data/labels/product_category_labels.csv",
    "sentiment": ROOT / "data/labels/sentiment_fingerprint_labels.csv",
}
OVERRIDES_PATH = ROOT / "data/labels/product_overrides.csv"

# These v1 rows predate rule_guess and therefore cannot be reached by the v2
# re-keying pass below.  Each replacement is accepted only while its own source
# still contains the recorded separator-bearing fragment.
LEGACY_SEPARATOR_RESTORATIONS = {
    "青森蘋果藍莓霜淇淋": ("青森蘋果x藍莓霜淇淋", ("青森蘋果x藍莓霜淇淋",)),
    "泰式奶茶起司蛋糕霜淇淋": ("泰式奶茶x起司蛋糕霜淇淋", ("泰式奶茶x起司蛋糕霜淇淋",)),
    "芭樂芋頭牛奶霜淇淋": ("芭樂x芋頭牛奶霜淇淋", ("芭樂x芋頭牛奶",)),
    "伊藤園抹茶咖啡綜合霜淇淋": (
        "伊藤園抹茶x咖啡綜合霜淇淋",
        ("伊藤園抹茶x咖啡綜合霜淇淋", "伊藤園抹茶+咖啡"),
    ),
}


def read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or ()), list(reader)


def write_rows(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\r\n")
        writer.writeheader()
        writer.writerows(rows)


@contextmanager
def legacy_separator_rules():
    current = identity._normalize_han_x_separator
    identity._normalize_han_x_separator = lambda text: identity._HAN_X_HAN_RE.sub(" ", text)
    try:
        yield
    finally:
        identity._normalize_han_x_separator = current


def raw_rule_items(post, *, legacy: bool):
    raw = identity._reply_product_extraction_text(post.product_name) if post.is_reply else post.product_name
    if legacy:
        with legacy_separator_rules():
            return identity.extract_products_and_prices_by_rules(raw, post.brand)
    return identity.extract_products_and_prices_by_rules(raw, post.brand)


def compact_without_x(value: str) -> str:
    return "".join(value.split()).replace("x", "").replace("X", "").replace("×", "")


def restore_legacy_separator_values(rows: list[dict[str, str]]) -> int:
    updated = 0
    for row in rows:
        restoration = LEGACY_SEPARATOR_RESTORATIONS.get(row.get("product_name", ""))
        if restoration is None:
            continue
        corrected, evidence_options = restoration
        source = unicodedata.normalize(
            "NFKC", f"{row.get('title', '')}\n{row.get('raw_name', '')}"
        ).casefold()
        if not any(
            unicodedata.normalize("NFKC", evidence).casefold() in source
            for evidence in evidence_options
        ):
            raise RuntimeError(
                f"separator evidence disappeared for {row['product_name']}: "
                f"{evidence_options}"
            )
        row["product_name"] = corrected
        updated += 1
    return updated


def migrate_product_names(raw_posts, rows: list[dict[str, str]]):
    by_fp: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_fp[row["fingerprint"]].append(row)
    fp_map: dict[str, str] = {}
    changed_inputs = set()
    judgement_updates = 0
    for post in raw_posts:
        old_items = raw_rule_items(post, legacy=True)
        new_items = raw_rule_items(post, legacy=False)
        if old_items == new_items:
            continue
        old_fp = product_name_fingerprint_v2(
            post.brand, post.title, post.product_name, rule_guess=format_rule_guess(old_items)
        )
        new_fp = product_name_fingerprint_v2(
            post.brand, post.title, post.product_name, rule_guess=format_rule_guess(new_items)
        )
        changed_inputs.add(old_fp)
        fp_map[old_fp] = new_fp
        group = by_fp.get(old_fp, [])
        if len(group) != len(new_items):
            continue
        for row in group:
            index = int(row.get("item_index") or 0)
            if index >= len(new_items):
                continue
            labelled = row.get("product_name") or ""
            corrected = new_items[index][0]
            if (
                not any(mark in labelled for mark in "xX×")
                and any(mark in corrected for mark in "xX×")
                and compact_without_x(labelled) == compact_without_x(corrected)
            ):
                row["product_name"] = corrected
                judgement_updates += 1
    rekeyed = 0
    for row in rows:
        replacement = fp_map.get(row["fingerprint"])
        if replacement:
            row["fingerprint"] = replacement
            rekeyed += 1
    legacy_updates = restore_legacy_separator_values(rows)
    return rekeyed, judgement_updates, legacy_updates, len(changed_inputs)


def build_state(raw_posts, *, legacy: bool):
    identity._cached_product_name_labels.cache_clear()
    if legacy:
        with legacy_separator_rules():
            posts = preprocess_posts(copy.deepcopy(raw_posts))
    else:
        posts = preprocess_posts(copy.deepcopy(raw_posts))
    groups = list(group_products(posts).values())
    post_positions = {id(item): index for index, item in enumerate(posts)}
    active: dict[str, set[str]] = {name: set() for name in CACHE_PATHS}
    for post in raw_posts:
        items = raw_rule_items(post, legacy=legacy)
        active["product_name"].add(product_name_fingerprint(post.brand, post.title, post.product_name))
        active["product_name"].add(product_name_fingerprint_v2(
            post.brand, post.title, post.product_name, rule_guess=format_rule_guess(items)
        ))
    for item in posts:
        body = _body_candidates([item])
        if (item.review_text or "").strip() and body:
            active["excerpt"].add(excerpt_fingerprint_v2(
                item.id, item.product_name, item.review_text or "", brand=item.brand,
                other_products=format_other_products(item.sibling_products), candidate_sentences=body,
            ))
        for comment in item.comments:
            active["sentiment"].add(comment_fingerprint_v2(item, comment))
    group_rows = []
    for group in groups:
        name = representative_product_name(group)
        comments, body = _rep_candidates(group), _body_candidates(group)
        if comments or body:
            active["comment_picks"].add(comment_picks_fingerprint_v2(
                group[0].brand, name, comments, body,
                other_products=other_products_for_group(group),
            ))
        active["category"].add(product_category_fingerprint(group[0].brand, name))
        group_rows.append((tuple(sorted(post_positions[id(item)] for item in group)), group[0].brand, name, group))
    return posts, group_rows, active


def context_maps(old_posts, new_posts, old_groups, new_groups):
    if len(old_posts) != len(new_posts):
        raise RuntimeError(f"product item count changed: {len(old_posts)} -> {len(new_posts)}")
    maps = {name: {} for name in ("excerpt", "sentiment", "comment_picks", "category")}
    name_map: dict[str, str] = {}
    for old, new in zip(old_posts, new_posts):
        if old.id != new.id:
            raise RuntimeError(f"post order changed: {old.id} -> {new.id}")
        if old.product_name != new.product_name:
            name_map[old.product_name] = new.product_name
        old_body, new_body = _body_candidates([old]), _body_candidates([new])
        if (old.review_text or "").strip() and old_body and new_body:
            old_fp = excerpt_fingerprint_v2(
                old.id, old.product_name, old.review_text or "", brand=old.brand,
                other_products=format_other_products(old.sibling_products), candidate_sentences=old_body,
            )
            new_fp = excerpt_fingerprint_v2(
                new.id, new.product_name, new.review_text or "", brand=new.brand,
                other_products=format_other_products(new.sibling_products), candidate_sentences=new_body,
            )
            maps["excerpt"][old_fp] = new_fp
        if len(old.comments) != len(new.comments):
            raise RuntimeError(f"comment count changed for {old.id}")
        for old_comment, new_comment in zip(old.comments, new.comments):
            maps["sentiment"][comment_fingerprint_v2(old, old_comment)] = comment_fingerprint_v2(new, new_comment)

    new_by_members = {members: (brand, name, group) for members, brand, name, group in new_groups}
    id_map: dict[str, str] = {}
    for members, brand, old_name, old_group in old_groups:
        if members not in new_by_members:
            raise RuntimeError(f"product group membership changed: {brand}::{old_name}")
        new_brand, new_name, new_group = new_by_members[members]
        id_map[f"{brand}::{old_name}"] = f"{new_brand}::{new_name}"
        old_comments, old_body = _rep_candidates(old_group), _body_candidates(old_group)
        new_comments, new_body = _rep_candidates(new_group), _body_candidates(new_group)
        if old_comments or old_body:
            old_fp = comment_picks_fingerprint_v2(
                brand, old_name, old_comments, old_body,
                other_products=other_products_for_group(old_group),
            )
            new_fp = comment_picks_fingerprint_v2(
                new_brand, new_name, new_comments, new_body,
                other_products=other_products_for_group(new_group),
            )
            maps["comment_picks"][old_fp] = new_fp
        maps["category"][product_category_fingerprint(brand, old_name)] = product_category_fingerprint(
            new_brand, new_name
        )
    return maps, name_map, id_map


JUDGEMENT_FIELDS = {
    "excerpt": ("source_indices", "rewrite"),
    "comment_picks": (
        "positive_rewrites", "negative_rewrites",
        "positive_body_rewrites", "negative_body_rewrites",
    ),
    "category": ("category",),
    "sentiment": ("llm_score", "llm_label", "is_relevant"),
}


def rekey_rows(layer, rows, fp_map, name_map):
    count = 0
    for row in rows:
        if layer == "category":
            replacement_name = name_map.get(row["product_name"])
            if replacement_name and replacement_name != row["product_name"]:
                row["product_name"] = replacement_name
                row["fingerprint"] = product_category_fingerprint(
                    row["brand"],
                    replacement_name,
                    prompt_version=row["prompt_version"],
                )
                count += 1
            continue
        replacement = fp_map.get(row["fingerprint"])
        if replacement and replacement != row["fingerprint"]:
            row["fingerprint"] = replacement
            if "product_name" in row and row["product_name"] in name_map:
                row["product_name"] = name_map[row["product_name"]]
            count += 1
    kept = {}
    deduplicated = 0
    for row in rows:
        key = (row["fingerprint"], row.get("item_index", ""))
        previous = kept.get(key)
        if previous is None:
            kept[key] = row
            continue
        fields = JUDGEMENT_FIELDS[layer]
        if any(previous.get(field, "") != row.get(field, "") for field in fields):
            raise RuntimeError(f"migration produced conflicting {layer} judgments for {key}")
        deduplicated += 1
    rows[:] = list(kept.values())
    return count, deduplicated


def orphan_counts(all_rows, active):
    return {name: sum(row["fingerprint"] not in active[name] for row in rows) for name, (_, rows) in all_rows.items()}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="rewrite caches and overrides")
    args = parser.parse_args()
    raw_posts = load_posts(ROOT / "data/posts.jsonl")
    all_rows = {name: read_rows(path) for name, path in CACHE_PATHS.items()}
    product_rows = all_rows["product_name"][1]
    product_rekeyed, judgement_updates, legacy_updates, candidate_fingerprints = migrate_product_names(
        raw_posts, product_rows
    )
    # The legacy extractor is the before-state only while v2 fingerprints still
    # need migration.  On a later value-only run it would resurrect the already
    # retired behaviour and can change the split-item count.
    old_posts, old_groups, old_active = build_state(
        raw_posts, legacy=product_rekeyed > 0
    )
    before_orphans = orphan_counts(all_rows, old_active)

    if args.apply:
        write_rows(CACHE_PATHS["product_name"], all_rows["product_name"][0], product_rows)
    identity._cached_product_name_labels.cache_clear()
    new_posts, new_groups, new_active = build_state(raw_posts, legacy=False)
    maps, name_map, id_map = context_maps(old_posts, new_posts, old_groups, new_groups)

    rekeyed = {"product_name": product_rekeyed}
    deduplicated = {"product_name": 0}
    for name in ("excerpt", "comment_picks", "category", "sentiment"):
        rekeyed[name], deduplicated[name] = rekey_rows(
            name, all_rows[name][1], maps[name], name_map
        )

    override_fields, override_rows = read_rows(OVERRIDES_PATH)
    override_count = 0
    for row in override_rows:
        replacement = id_map.get(row["product_id"])
        if replacement and replacement != row["product_id"]:
            row["product_id"] = replacement
            row["productName"] = replacement.split("::", 1)[1]
            override_count += 1

    if args.apply:
        for name in ("excerpt", "comment_picks", "category", "sentiment"):
            write_rows(CACHE_PATHS[name], all_rows[name][0], all_rows[name][1])
        write_rows(OVERRIDES_PATH, override_fields, override_rows)
    after_orphans = orphan_counts(all_rows, new_active)
    print(json.dumps({
        "applied": args.apply,
        "candidate_fingerprints": candidate_fingerprints,
        "product_name_judgements_separator_only_updated": judgement_updates,
        "legacy_product_name_values_updated": legacy_updates,
        "rekeyed_rows": rekeyed,
        "deduplicated_identical_rows": deduplicated,
        "override_rows": override_count,
        "orphans_before": before_orphans,
        "orphans_after": after_orphans,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
