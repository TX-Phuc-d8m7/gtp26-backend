#!/usr/bin/env python3
"""Backfill foods.img_url with web image search results uploaded to GCS.

Default mode is dry-run: search image candidates and write a report without
uploading or updating the database. Use --apply to upload and persist img_url.
Google Custom Search is preferred when configured; open-license sources remain
as a fallback.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.db.session import AsyncSessionLocal, engine
from app.modules.foods.models import Food


GOOGLE_CUSTOM_SEARCH_API_URL = "https://www.googleapis.com/customsearch/v1"
OPENVERSE_API_URL = "https://api.openverse.org/v1/images/"
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
DEFAULT_ATTRIBUTION_PATH = (
    PROJECT_ROOT / "standard-data" / "image-attribution" / "food_image_sources.json"
)
DEFAULT_REPORT_PATH = (
    PROJECT_ROOT / "standard-data" / "image-attribution" / "food_image_backfill_report.json"
)

USER_AGENT = "food-recommendation-system/1.0 (image backfill; educational demo)"
SAFE_LICENSE_PREFIXES = (
    "cc0",
    "pdm",
    "public-domain",
    "publicdomain",
    "cc-by",
    "by",
    "cc-by-sa",
    "by-sa",
)
BLOCKED_LICENSE_MARKERS = (
    "nc",
    "noncommercial",
    "non-commercial",
    "nd",
    "no-derivatives",
    "noderivatives",
)
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_FILE_SIZE_BYTES = 5 * 1024 * 1024
FOOD_TOKEN_STOPWORDS = {
    "an",
    "chay",
    "chien",
    "hap",
    "kho",
    "luoc",
    "mon",
    "nuong",
    "sot",
    "trang",
    "tron",
    "viet",
    "vietnam",
    "vietnamese",
    "xao",
}
FOOD_RELEVANCE_SYNONYMS = {
    "banh mi": {"sandwich", "baguette"},
    "bun": {"vermicelli", "noodle", "noodles"},
    "ca": {"fish"},
    "cao lau": {"noodle", "noodles"},
    "chao": {"porridge", "congee"},
    "com": {"rice"},
    "goi": {"salad"},
    "hu tieu": {"noodle", "noodles", "soup"},
    "mi": {"noodle", "noodles"},
    "mien": {"vermicelli", "noodle", "noodles"},
    "pho": {"noodle", "noodles", "soup"},
    "sup": {"soup"},
    "xoi": {"sticky", "rice"},
}
FOOD_QUERY_FALLBACKS = {
    "banh mi": ["banh mi Vietnamese sandwich", "Vietnamese baguette"],
    "bun": ["Vietnamese bun noodles", "Vietnamese vermicelli bowl"],
    "ca": ["Vietnamese fish dish"],
    "cao lau": ["cao lau Vietnamese noodles"],
    "chao": ["Vietnamese rice porridge", "Vietnamese congee"],
    "com": ["Vietnamese rice dish"],
    "goi": ["Vietnamese salad"],
    "hu tieu": ["hu tieu Vietnamese noodle soup"],
    "mi": ["Vietnamese noodles"],
    "mien": ["Vietnamese glass noodles"],
    "pho": ["pho Vietnamese food", "Vietnamese pho", "Vietnamese noodle soup"],
    "sup": ["Vietnamese soup"],
    "xoi": ["Vietnamese sticky rice"],
}


@dataclass
class ImageCandidate:
    provider: str
    image_url: str
    source_url: str
    creator: str | None
    license: str
    license_url: str | None
    title: str | None = None


@dataclass
class DownloadedImage:
    content: bytes
    content_type: str
    filename: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_html(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _normalize_license(value: str | None, license_url: str | None = None) -> str:
    joined = " ".join(part for part in [value or "", license_url or ""] if part)
    normalized = joined.lower()
    normalized = normalized.replace("creative commons", "cc")
    normalized = normalized.replace("public domain mark", "pdm")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    normalized = re.sub(r"-[0-9]+(?:-[0-9]+)?$", "", normalized)
    return normalized


def is_safe_license(value: str | None, license_url: str | None = None) -> bool:
    normalized = _normalize_license(value, license_url)
    if not normalized:
        return False
    if any(marker in normalized.split("-") for marker in {"nc", "nd"}):
        return False
    if any(marker in normalized for marker in BLOCKED_LICENSE_MARKERS):
        return False
    return any(
        normalized == prefix or normalized.startswith(f"{prefix}-")
        for prefix in SAFE_LICENSE_PREFIXES
    )


def fetch_json(url: str, params: dict[str, Any], *, timeout: int = 20) -> dict[str, Any]:
    request_url = f"{url}?{urlencode(params)}"
    request = Request(request_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def google_custom_search_config() -> tuple[str | None, str | None]:
    api_key = (
        os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY")
        or os.getenv("GOOGLE_CSE_API_KEY")
        or os.getenv("GOOGLE_SEARCH_API_KEY")
    )
    search_engine_id = (
        os.getenv("GOOGLE_CUSTOM_SEARCH_CX")
        or os.getenv("GOOGLE_CSE_ID")
        or os.getenv("GOOGLE_SEARCH_ENGINE_ID")
    )
    return api_key, search_engine_id


def query_variants(food_name: str) -> list[str]:
    normalized_name = normalize_search_text(food_name)
    variants = [
        f"{food_name} Vietnamese food",
        f"{food_name} món ăn Việt Nam",
        food_name,
    ]
    for phrase, fallbacks in FOOD_QUERY_FALLBACKS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", normalized_name):
            variants.extend(fallbacks)

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        key = normalize_search_text(variant)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(variant)
    return deduped


def normalize_search_text(value: str | None) -> str:
    if not value:
        return ""
    text = unicodedata.normalize("NFD", value)
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    text = text.lower().replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def significant_food_tokens(food_name: str) -> set[str]:
    normalized_name = normalize_search_text(food_name)
    tokens = set(normalized_name.split())
    relevance_tokens = {
        token
        for token in tokens
        if len(token) >= 3 and token not in FOOD_TOKEN_STOPWORDS
    }
    for phrase, synonyms in FOOD_RELEVANCE_SYNONYMS.items():
        if re.search(rf"\b{re.escape(phrase)}\b", normalized_name):
            relevance_tokens.update(synonyms)
    return relevance_tokens


def candidate_matches_food_name(food_name: str, candidate: ImageCandidate) -> bool:
    tokens = significant_food_tokens(food_name)
    if not tokens:
        return True
    candidate_text = normalize_search_text(
        " ".join(
            part
            for part in [
                candidate.title,
                candidate.source_url,
                candidate.image_url,
            ]
            if part
        )
    )
    return any(token in candidate_text.split() for token in tokens)


def search_google_images(food_name: str, *, limit: int) -> list[ImageCandidate]:
    api_key, search_engine_id = google_custom_search_config()
    if not api_key or not search_engine_id:
        print(
            "  ⚠️ Google image search chưa cấu hình "
            "(GOOGLE_CUSTOM_SEARCH_API_KEY + GOOGLE_CUSTOM_SEARCH_CX)."
        )
        return []

    candidates: list[ImageCandidate] = []
    for query in query_variants(food_name):
        try:
            payload = fetch_json(
                GOOGLE_CUSTOM_SEARCH_API_URL,
                {
                    "key": api_key,
                    "cx": search_engine_id,
                    "q": query,
                    "searchType": "image",
                    "num": min(max(limit, 1), 10),
                    "safe": "active",
                },
            )
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  ⚠️ Google image search lỗi query '{query}': {exc}")
            continue

        for item in payload.get("items", []) or []:
            image_url = item.get("link")
            if not image_url:
                continue
            image_meta = item.get("image") or {}
            candidates.append(
                ImageCandidate(
                    provider="google_custom_search",
                    image_url=image_url,
                    source_url=image_meta.get("contextLink") or item.get("displayLink") or image_url,
                    creator=None,
                    license="unspecified",
                    license_url=None,
                    title=item.get("title") or item.get("snippet"),
                )
            )
        if candidates:
            break
    return candidates


def search_openverse(food_name: str, *, limit: int) -> list[ImageCandidate]:
    candidates: list[ImageCandidate] = []
    for query in query_variants(food_name):
        try:
            payload = fetch_json(
                OPENVERSE_API_URL,
                {
                    "q": query,
                    "page_size": limit,
                    "mature": "false",
                    "license_type": "all",
                },
            )
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  ⚠️ Openverse lỗi query '{query}': {exc}")
            continue

        for item in payload.get("results", []) or []:
            image_url = item.get("url")
            license_name = item.get("license") or ""
            license_url = item.get("license_url")
            if not image_url or not is_safe_license(license_name, license_url):
                continue
            candidates.append(
                ImageCandidate(
                    provider="openverse",
                    image_url=image_url,
                    source_url=item.get("foreign_landing_url") or image_url,
                    creator=item.get("creator"),
                    license=license_name,
                    license_url=license_url,
                    title=item.get("title"),
                )
            )
        if candidates:
            break
    return candidates


def _extmetadata_value(metadata: dict[str, Any], key: str) -> str | None:
    raw = metadata.get(key) or {}
    if isinstance(raw, dict):
        return _clean_html(raw.get("value"))
    return _clean_html(raw)


def search_wikimedia(food_name: str, *, limit: int) -> list[ImageCandidate]:
    candidates: list[ImageCandidate] = []
    for query in query_variants(food_name):
        try:
            payload = fetch_json(
                WIKIMEDIA_API_URL,
                {
                    "action": "query",
                    "format": "json",
                    "generator": "search",
                    "gsrnamespace": 6,
                    "gsrsearch": query,
                    "gsrlimit": limit,
                    "prop": "imageinfo",
                    "iiprop": "url|mime|extmetadata",
                    "origin": "*",
                },
            )
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            print(f"  ⚠️ Wikimedia lỗi query '{query}': {exc}")
            continue

        pages = (payload.get("query") or {}).get("pages") or {}
        for page in pages.values():
            infos = page.get("imageinfo") or []
            if not infos:
                continue
            info = infos[0]
            if info.get("mime") not in ALLOWED_CONTENT_TYPES:
                continue
            metadata = info.get("extmetadata") or {}
            license_name = (
                _extmetadata_value(metadata, "LicenseShortName")
                or _extmetadata_value(metadata, "UsageTerms")
                or ""
            )
            license_url = _extmetadata_value(metadata, "LicenseUrl")
            if not is_safe_license(license_name, license_url):
                continue
            image_url = info.get("url")
            if not image_url:
                continue
            candidates.append(
                ImageCandidate(
                    provider="wikimedia_commons",
                    image_url=image_url,
                    source_url=info.get("descriptionurl") or image_url,
                    creator=_extmetadata_value(metadata, "Artist")
                    or _extmetadata_value(metadata, "Credit"),
                    license=license_name,
                    license_url=license_url,
                    title=_clean_html(page.get("title")),
                )
            )
        if candidates:
            break
    return candidates


def find_candidates(food_name: str, *, limit: int, source: str) -> list[ImageCandidate]:
    provider_results: list[ImageCandidate] = []
    if source in {"google", "all"}:
        provider_results.extend(search_google_images(food_name, limit=limit))
    if source in {"open-license", "openverse", "all"}:
        provider_results.extend(search_openverse(food_name, limit=limit))
    if source in {"open-license", "wikimedia", "all"}:
        provider_results.extend(search_wikimedia(food_name, limit=limit))

    seen: set[str] = set()
    merged: list[ImageCandidate] = []
    for candidate in provider_results:
        if candidate.image_url in seen:
            continue
        if not candidate_matches_food_name(food_name, candidate):
            continue
        seen.add(candidate.image_url)
        merged.append(candidate)
    return merged


def _filename_from_url(url: str, content_type: str) -> str:
    path_name = Path(urlparse(url).path).name
    if path_name and "." in path_name:
        return path_name
    fallback_ext = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }.get(content_type, ".jpg")
    return f"downloaded{fallback_ext}"


def download_image(candidate: ImageCandidate, *, timeout: int = 30) -> DownloadedImage:
    request = Request(candidate.image_url, headers={"User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        content_type = (response.headers.get("Content-Type") or "").split(";")[0].lower()
        if content_type == "image/jpg":
            content_type = "image/jpeg"
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f"Content-Type không hợp lệ: {content_type or '<missing>'}")

        content = response.read(MAX_FILE_SIZE_BYTES + 1)
        if len(content) > MAX_FILE_SIZE_BYTES:
            raise ValueError(f"Ảnh quá lớn: {len(content)} bytes")
        if not content:
            raise ValueError("Ảnh tải về rỗng")

        return DownloadedImage(
            content=content,
            content_type=content_type,
            filename=_filename_from_url(candidate.image_url, content_type),
        )


def load_json_list(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if isinstance(payload, list):
        return payload
    return []


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def upsert_attribution(path: Path, record: dict[str, Any]) -> None:
    rows = load_json_list(path)
    food_id = record["food_id"]
    updated = False
    for index, row in enumerate(rows):
        if row.get("food_id") == food_id:
            rows[index] = record
            updated = True
            break
    if not updated:
        rows.append(record)
    rows.sort(key=lambda item: item.get("food_name", ""))
    write_json(path, rows)


async def load_foods(*, food_name: str | None, limit: int | None, overwrite: bool) -> list[Food]:
    async with AsyncSessionLocal() as db:
        stmt = select(Food).order_by(Food.name)
        if food_name:
            stmt = stmt.where(Food.name.ilike(f"%{food_name}%"))
        if not overwrite:
            stmt = stmt.where((Food.img_url.is_(None)) | (Food.img_url == ""))
        if limit:
            stmt = stmt.limit(limit)
        result = await db.execute(stmt)
        return list(result.scalars().all())


async def apply_image_to_food(
    food_id: uuid.UUID,
    candidate: ImageCandidate,
    downloaded: DownloadedImage,
) -> str:
    from app.integrations.google_storage import delete_food_image, upload_food_image

    async with AsyncSessionLocal() as db:
        food = await db.get(Food, food_id)
        if food is None:
            raise ValueError(f"Không tìm thấy food_id={food_id}")

        old_url = food.img_url
        new_url = upload_food_image(
            file_content=downloaded.content,
            original_filename=downloaded.filename,
            content_type=downloaded.content_type,
            food_id=str(food.id),
        )
        food.img_url = new_url
        await db.commit()

        if old_url and old_url != new_url:
            delete_food_image(old_url)

        return new_url


async def process_food(
    food: Food,
    *,
    apply: bool,
    candidate_limit: int,
    source: str,
    attribution_path: Path,
) -> dict[str, Any]:
    print(f"\n🔎 {food.name}")
    candidates = find_candidates(food.name, limit=candidate_limit, source=source)
    if not candidates:
        print("  ⚠️ Không tìm thấy ảnh phù hợp.")
        return {
            "food_id": str(food.id),
            "food_name": food.name,
            "status": "skipped",
            "reason": "no_candidate",
        }

    for candidate in candidates:
        print(
            "  • "
            f"{candidate.provider} | {candidate.license} | "
            f"{candidate.source_url}"
        )
        if not apply:
            return {
                "food_id": str(food.id),
                "food_name": food.name,
                "status": "dry_run_candidate",
                "candidate": asdict(candidate),
            }

        try:
            downloaded = download_image(candidate)
            img_url = await apply_image_to_food(food.id, candidate, downloaded)
        except Exception as exc:
            print(f"    ⚠️ Bỏ candidate vì lỗi tải/upload: {exc}")
            continue

        attribution = {
            "food_id": str(food.id),
            "food_name": food.name,
            "img_url": img_url,
            "source_url": candidate.source_url,
            "provider": candidate.provider,
            "creator": candidate.creator,
            "license": candidate.license,
            "license_url": candidate.license_url,
            "original_image_url": candidate.image_url,
            "uploaded_at": _now_iso(),
        }
        upsert_attribution(attribution_path, attribution)
        print(f"  ✅ Uploaded: {img_url}")
        return {
            "food_id": str(food.id),
            "food_name": food.name,
            "status": "uploaded",
            "img_url": img_url,
            "candidate": asdict(candidate),
        }

    return {
        "food_id": str(food.id),
        "food_name": food.name,
        "status": "skipped",
        "reason": "all_candidates_failed",
        "candidate_count": len(candidates),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Preview only; do not upload/update DB")
    mode.add_argument("--apply", action="store_true", help="Upload to GCS and update foods.img_url")
    parser.add_argument("--limit", type=int, default=5, help="Maximum foods to process")
    parser.add_argument("--food-name", help="Only process foods whose name contains this text")
    parser.add_argument("--overwrite", action="store_true", help="Also process foods that already have img_url")
    parser.add_argument("--sleep", type=float, default=1.0, help="Seconds to sleep between foods")
    parser.add_argument("--candidate-limit", type=int, default=5, help="Candidates to request per provider query")
    parser.add_argument(
        "--source",
        choices=["google", "open-license", "openverse", "wikimedia", "all"],
        default="all",
        help="Image source. Default: Google first, then open-license fallback",
    )
    parser.add_argument("--attribution-path", type=Path, default=DEFAULT_ATTRIBUTION_PATH)
    parser.add_argument("--report-path", type=Path, default=DEFAULT_REPORT_PATH)
    return parser.parse_args()


async def main() -> None:
    args = parse_args()
    apply = bool(args.apply)
    mode_label = "APPLY" if apply else "DRY-RUN"
    print(f"🖼️  Food image backfill mode: {mode_label}")

    foods = await load_foods(
        food_name=args.food_name,
        limit=args.limit,
        overwrite=args.overwrite,
    )
    if not foods:
        print("✨ Không có món nào cần xử lý.")
        return

    print(f"📦 Sẽ xử lý {len(foods)} món.")
    report = {
        "mode": mode_label,
        "started_at": _now_iso(),
        "finished_at": None,
        "source": args.source,
        "total": len(foods),
        "results": [],
    }

    try:
        for index, food in enumerate(foods, start=1):
            print(f"\n[{index}/{len(foods)}]")
            result = await process_food(
                food,
                apply=apply,
                candidate_limit=args.candidate_limit,
                source=args.source,
                attribution_path=args.attribution_path,
            )
            report["results"].append(result)
            write_json(args.report_path, report)
            if args.sleep > 0 and index < len(foods):
                time.sleep(args.sleep)
    finally:
        report["finished_at"] = _now_iso()
        write_json(args.report_path, report)
        await engine.dispose()

    status_counts: dict[str, int] = {}
    for result in report["results"]:
        status = result.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1
    print("\n✅ Hoàn tất.")
    print(f"📄 Report: {args.report_path}")
    if apply:
        print(f"📄 Attribution: {args.attribution_path}")
    print(f"📊 Summary: {status_counts}")


if __name__ == "__main__":
    asyncio.run(main())
