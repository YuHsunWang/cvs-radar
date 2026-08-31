from __future__ import annotations

import tomllib
from fnmatch import fnmatch
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "datasets.toml"
REQUIRED_FIELDS = {
    "name",
    "layer",
    "path",
    "format",
    "producing_owner",
    "partition_columns",
    "primary_key",
    "timezone",
    "update_frequency",
    "retention",
    "optional",
}
LAYERS = {"raw", "staging", "curated", "generated"}
DATA_SUFFIXES = {".csv", ".db", ".json", ".jsonl", ".parquet", ".sqlite", ".sqlite3"}


def _datasets() -> list[dict[str, object]]:
    with CATALOG.open("rb") as handle:
        payload = tomllib.load(handle)
    return payload["datasets"]


def test_dataset_catalog_has_required_contract_fields() -> None:
    datasets = _datasets()
    assert datasets, "the persisted-dataset catalog must not be empty"
    assert len({item["name"] for item in datasets}) == len(datasets)

    for item in datasets:
        missing = REQUIRED_FIELDS - item.keys()
        assert not missing, f"{item.get('name', '<unnamed>')} missing {sorted(missing)}"
        assert item["layer"] in LAYERS
        assert isinstance(item["partition_columns"], list)
        assert isinstance(item["primary_key"], list)
        assert isinstance(item["optional"], bool)
        if not item["primary_key"]:
            assert item.get("known_gap"), f"{item['name']} must explain its missing key"


def test_every_non_optional_dataset_path_exists() -> None:
    for item in _datasets():
        relative = Path(str(item["path"]))
        assert not relative.is_absolute(), f"{item['name']} must use a repo-relative path"
        assert ".." not in relative.parts, f"{item['name']} escapes the repository"

        resolved = ROOT / relative
        if not item["optional"]:
            assert resolved.exists(), f"required dataset path does not exist: {relative}"

        pattern = item.get("file_pattern")
        if pattern and resolved.exists():
            assert resolved.is_dir(), f"patterned dataset path is not a directory: {relative}"
            assert any(resolved.glob(str(pattern))), (
                f"dataset pattern has no files: {relative}/{pattern}"
            )


def test_every_persisted_data_file_in_known_homes_is_cataloged() -> None:
    candidates: set[Path] = set()
    for relative_root in ("data", "outputs", "artifacts"):
        candidates.update(
            path.relative_to(ROOT)
            for path in (ROOT / relative_root).rglob("*")
            if path.is_file() and path.suffix.lower() in DATA_SUFFIXES
        )
    candidates.update(
        path.relative_to(ROOT)
        for path in ROOT.iterdir()
        if path.is_file() and path.suffix.lower() in DATA_SUFFIXES - {".json"}
    )
    candidates.update(
        path.relative_to(ROOT)
        for path in (ROOT / "web" / "public" / "data.json", ROOT / "web" / "out" / "data.json")
        if path.exists()
    )

    datasets = _datasets()

    def cataloged(candidate: Path) -> bool:
        for item in datasets:
            catalog_path = Path(str(item["path"]))
            pattern = item.get("file_pattern")
            if pattern:
                if candidate.parent == catalog_path and fnmatch(candidate.name, str(pattern)):
                    return True
            elif candidate == catalog_path:
                return True
        return False

    uncovered = sorted(str(path) for path in candidates if not cataloged(path))
    assert not uncovered, f"persisted data files missing from catalog: {uncovered}"
