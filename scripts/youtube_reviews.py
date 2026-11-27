"""Daily YouTube step: new taste-test videos -> creators' verdicts in data/labels/youtube_reviews.csv.

For each new video from the channels in config.yaml (YOUTUBE):
  1. list it with the official Data API (key in ~/.config/youtube/env),
  2. download the audio with yt-dlp and transcribe it locally with faster-whisper,
  3. let Codex extract one row per product, check the rows mechanically,
  4. let a second Codex pass check each row against the transcript,
  5. append the surviving rows; record the video in youtube_videos.csv.

Audio and transcripts stay in ~/.cache/cvs-radar/youtube and never enter the
repo. Any failure leaves the CSVs as they were, and the cron treats this step as
optional, so the PTT publish never waits on YouTube.

Env overrides: MODEL RUNNER YOUTUBE_ENV CACHE MAX_VIDEOS LOOKBACK_DAYS (a one-off backfill)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cvs_radar.config import YOUTUBE  # noqa: E402
from cvs_radar.youtube_reviews import (  # noqa: E402
    REVIEW_FIELDS, REVIEWS_PATH, VIDEO_FIELDS, VIDEOS_PATH, append_rows, load_videos, review_errors,
)

API = "https://www.googleapis.com/youtube/v3/"
MODEL = os.environ.get("MODEL", "gpt-5.6-luna")
RUNNER = os.environ.get("RUNNER", str(Path.home() / ".claude/skills/codex-direct/scripts/run-codex.mjs"))
CACHE = Path(os.environ.get("CACHE", Path.home() / ".cache/cvs-radar/youtube"))
PROMPTS = ROOT / "scripts" / "prompts"
CVS_TITLE = re.compile(r"超商|便利商店|7-?11|小七|711|全家|萊爾富|OK超商|FamilyMart|7-Eleven", re.I)
FOREIGN_TITLE = re.compile(r"日本|韓國|Lawson|羅森|泰國|香港")
WHISPER_PROMPT = "以下是繁體中文的超商新品開箱影片，提到7-11、全家、萊爾富的商品、價格和好不好吃。"


def log(message: str) -> None:
    print(f"[youtube] {message}", flush=True)


def api_key() -> str:
    if key := os.environ.get("YOUTUBE_API_KEY"):
        return key
    env = Path(os.environ.get("YOUTUBE_ENV", Path.home() / ".config/youtube/env"))
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("YOUTUBE_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise SystemExit(f"YOUTUBE_API_KEY not found in {env}")


def api(endpoint: str, key: str, **params: str | int) -> dict:
    url = API + endpoint + "?" + urllib.parse.urlencode({**params, "key": key})
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def iso_seconds(duration: str) -> int:
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    days, hours, minutes, seconds = (int(part or 0) for part in match.groups()) if match else (0, 0, 0, 0)
    return ((days * 24 + hours) * 60 + minutes) * 60 + seconds


def is_cvs_title(title: str) -> bool:
    return bool(CVS_TITLE.search(title)) and not FOREIGN_TITLE.search(title)


def new_videos(key: str, seen: set[str], lookback_days: int) -> list[dict]:
    """Taste-test uploads inside the window that the ledger has not recorded, oldest first."""
    since = datetime.now(timezone.utc) - timedelta(days=lookback_days)
    channels = {channel["id"]: channel["name"] for channel in YOUTUBE["channels"]}
    found = []
    info = api("channels", key, part="contentDetails", id=",".join(channels))
    for channel in info["items"]:
        playlist, token = channel["contentDetails"]["relatedPlaylists"]["uploads"], ""
        for _ in range(4):  # 200 uploads is far past any lookback window
            page = api("playlistItems", key, part="snippet", playlistId=playlist, maxResults=50, **({"pageToken": token} if token else {}))
            older = False
            for item in page["items"]:
                snippet = item["snippet"]
                published = datetime.fromisoformat(snippet["publishedAt"].replace("Z", "+00:00"))
                older = older or published < since
                video_id = snippet["resourceId"]["videoId"]
                if published >= since and video_id not in seen and is_cvs_title(snippet["title"]):
                    found.append({"video_id": video_id, "channel": channels[channel["id"]],
                                  "published": published.date().isoformat(), "title": snippet["title"],
                                  "description": snippet.get("description", "")[:1500]})
            token = page.get("nextPageToken", "")
            if older or not token:
                break
    if found:
        details = {}
        for start in range(0, len(found), 50):
            batch = ",".join(video["video_id"] for video in found[start:start + 50])
            details.update({item["id"]: item for item in api("videos", key, part="contentDetails", id=batch)["items"]})
        for video in found:
            video["duration"] = iso_seconds(details.get(video["video_id"], {}).get("contentDetails", {}).get("duration", "PT0S"))
        # Shorts carry no real verdicts and two-hour streams would eat the night.
        found = [video for video in found if 120 <= video["duration"] <= 3600]
    return sorted(found, key=lambda video: video["published"])


def transcript(video: dict) -> Path:
    """Cached `m:ss text` transcript; the audio is deleted once it is written."""
    CACHE.mkdir(parents=True, exist_ok=True)
    out = CACHE / f"{video['video_id']}.txt"
    if out.exists() and out.stat().st_size:
        return out
    audio = CACHE / f"{video['video_id']}.m4a"
    subprocess.run(
        ["yt-dlp", "--no-update", "-q", "-f", "bestaudio[ext=m4a]/bestaudio", "-o", str(audio),
         f"https://www.youtube.com/watch?v={video['video_id']}"],
        check=True, timeout=900,
    )
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    from faster_whisper import WhisperModel

    model = WhisperModel("medium", device="cpu", compute_type="int8")
    segments, _info = model.transcribe(str(audio), language="zh", vad_filter=True, beam_size=5, initial_prompt=WHISPER_PROMPT)
    lines = [f"{int(s.start) // 60}:{int(s.start) % 60:02d} {s.text.strip()}" for s in segments]
    tmp = out.with_suffix(".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(out)
    audio.unlink(missing_ok=True)
    return out


def codex(prompt_name: str, video_id: str, work: Path) -> None:
    prompt = (PROMPTS / prompt_name).read_text(encoding="utf-8").replace("__ID__", video_id)
    prompt_path = work / f"{video_id}.{prompt_name}"
    prompt_path.write_text(prompt, encoding="utf-8")
    subprocess.run(
        ["node", RUNNER, str(prompt_path), "--cwd", str(work), "--model", MODEL, "--allow-non-git",
         "--timeout", "1800000", "--inactivity-timeout", "600000"],
        check=True, stdout=subprocess.DEVNULL, timeout=2000,
    )


def read_json_list(path: Path) -> list:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"{path.name} is not a JSON array")
    return data


def site_product_ids() -> set[str]:
    data = ROOT / "web" / "public" / "data.json"
    if not data.exists():
        return set()
    return {p["id"] for p in json.loads(data.read_text(encoding="utf-8"))["products"]}


def review_rows(video: dict, work: Path, known_ids: set[str]) -> list[dict]:
    """Extract, check mechanically, verify against the transcript; return the rows to publish."""
    video_id = video["video_id"]
    (work / f"{video_id}.transcript.txt").write_text(transcript(video).read_text(encoding="utf-8"), encoding="utf-8")
    (work / f"{video_id}.meta.json").write_text(json.dumps(
        {key: video[key] for key in ("channel", "published", "title", "description", "duration")}, ensure_ascii=False, indent=1), encoding="utf-8")
    (work / "candidates.txt").write_text("\n".join(sorted(known_ids)) + "\n", encoding="utf-8")

    codex("youtube-extract.md", video_id, work)
    rows = []
    for item in read_json_list(work / f"{video_id}.extract.json"):
        row = {key: str(item.get(key, "") if item.get(key) is not None else "").strip() for key in REVIEW_FIELDS}
        row.update(video_id=video_id, channel=video["channel"], video_date=video["published"])
        if row["product_id"] not in known_ids:
            row["product_id"] = ""
        if errors := review_errors(row, video["duration"]):
            log(f"{video_id}: dropped {row['product_name'] or '?'}: {'; '.join(errors)}")
            continue
        rows.append(row)
    if not rows:
        return []

    (work / f"{video_id}.extract.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    codex("youtube-verify.md", video_id, work)
    verdicts = {v.get("index"): v for v in read_json_list(work / f"{video_id}.verify.json") if isinstance(v, dict)}
    kept = []
    for index, row in enumerate(rows):
        verdict = verdicts.get(index, {})
        if verdict.get("keep") is True:
            kept.append(row)
        else:  # a missing verdict counts as a rejection
            log(f"{video_id}: verifier dropped {row['product_name']}: {verdict.get('reason', 'no verdict')}")
    return kept


def main() -> int:
    argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter).parse_args()
    key = api_key()
    reviews_path, videos_path = ROOT / REVIEWS_PATH, ROOT / VIDEOS_PATH
    seen = set(load_videos(videos_path))
    videos = new_videos(key, seen, int(os.environ.get("LOOKBACK_DAYS", YOUTUBE.get("lookback_days", 30))))
    limit = int(os.environ.get("MAX_VIDEOS", YOUTUBE.get("max_videos_per_run", 3)))
    log(f"{len(videos)} new video(s); processing up to {limit}")
    known_ids = site_product_ids()
    added = 0
    for video in videos[:limit]:
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        try:
            with tempfile.TemporaryDirectory(prefix="youtube-reviews.") as tmp:
                rows = review_rows(video, Path(tmp), known_ids)
        except Exception as error:  # noqa: BLE001 - one bad video must not stop the rest
            log(f"{video['video_id']}: FAILED {type(error).__name__}: {error}")
            # ponytail: a failed video is not retried; delete its ledger line to retry it.
            append_rows(videos_path, VIDEO_FIELDS, [{**video, "status": "failed", "processed_at": now}])
            continue
        append_rows(reviews_path, REVIEW_FIELDS, rows)
        known_ids |= {row["product_id"] or f"{row['brand']}::{row['product_name']}" for row in rows}  # later videos can match these
        append_rows(videos_path, VIDEO_FIELDS, [{**video, "status": "done" if rows else "empty", "processed_at": now}])
        added += len(rows)
        log(f"{video['video_id']} {video['channel']}: {len(rows)} review(s) — {video['title'][:40]}")
    log(f"DONE. reviews added={added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
