import os
import re
import string
from datetime import UTC, datetime

from unidecode import unidecode

NO_RECORDING_MARKER = "(No recording available)"
ARCHIVE_DETAILS_URL = "https://archive.org/details/"


def build_archive_id(publisher_name: str, prefix: str, pub_inc: int = 1) -> str:
    """Build the archive.org item id for a performance (``pub_inc`` > 1 for a publisher's later sets)."""
    slug = publisher_name.lower().replace(" ", "-")
    punct_chars = re.escape(string.punctuation)
    slug = re.sub(r"[" + punct_chars + "]", "-", slug)
    slug = unidecode(slug).replace(" ", "-")

    if pub_inc > 1:
        slug = f"{slug}-{pub_inc}"

    return prefix + slug


def predict_archive_ids(results: list[dict], prefix: str) -> dict[str, str]:
    """Predict the archive.org item id of every set that has recordings, keyed by the set's ``url``.

    Mirrors the numbering in live-coding-archiver.py (a publisher's repeat sets get -2, -3, ... where names that
    differ only in case or punctuation count as the same publisher) and assumes
    every set with recordings is uploaded. Used for previewing; the archiver records the real ids.
    """
    ids: dict[str, str] = {}
    processed_publishers: list[str] = []
    pub_inc = 1

    for result in results:
        name = result["publisher_name"]
        # repeat publishers are identified by their archive id slug, matching live-coding-archiver.py
        key = build_archive_id(name, "")
        pub_inc = pub_inc + 1 if key in processed_publishers else 1

        if result.get("recordings"):
            ids[result["url"]] = build_archive_id(name, prefix, pub_inc)
            if key not in processed_publishers:
                processed_publishers.append(key)

    return ids


def _parse_start(starts_at: str) -> datetime:
    """Parse an ISO-8601 timestamp (``Z`` or offset) into an aware UTC datetime."""
    parsed = datetime.fromisoformat(starts_at)
    if parsed.tzinfo is None:
        # metadata timestamps are UTC; treat naive values the same way
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clean_description(description: str | None) -> str:
    return (description or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def build_setlist(title: str, results: list[dict], archive_ids: dict[str, str] | None = None) -> str:
    """Build the set list text: the stream title, then every set in chronological (UTC) order.

    ``archive_ids`` maps a set's ``url`` to its archive.org item id; sets found there get an Archive line.
    """
    archive_ids = archive_ids or {}
    # sorted() is stable, so sets with identical start times keep their metadata order
    ordered = sorted(results, key=lambda r: _parse_start(r["starts_at"]))

    blocks = [title]
    for result in ordered:
        start = _parse_start(result["starts_at"]).strftime("%Y-%m-%d %H:%M UTC")
        lines = [
            start,
            f"Artist: {result['publisher_name']}",
            f"Title: {result['title']}",
            f"Description: {_clean_description(result.get('description'))}",
        ]
        archive_id = archive_ids.get(result.get("url", ""))
        if archive_id:
            lines.append(f"Archive: {ARCHIVE_DETAILS_URL}{archive_id}")
        if not result.get("recordings"):
            lines.append(NO_RECORDING_MARKER)
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def write_setlist(title: str, results: list[dict], path: str, archive_ids: dict[str, str] | None = None) -> str:
    """Write the set list to ``path`` (creating parent directories) and return the path."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(build_setlist(title, results, archive_ids))

    return path
