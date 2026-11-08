import os
from datetime import UTC, datetime

NO_RECORDING_MARKER = "(No recording available)"


def _parse_start(starts_at: str) -> datetime:
    """Parse an ISO-8601 timestamp (``Z`` or offset) into an aware UTC datetime."""
    parsed = datetime.fromisoformat(starts_at)
    if parsed.tzinfo is None:
        # metadata timestamps are UTC; treat naive values the same way
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _clean_description(description: str | None) -> str:
    return (description or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def build_setlist(title: str, results: list[dict]) -> str:
    """Build the set list text: the stream title, then every set in chronological (UTC) order."""
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
        if not result.get("recordings"):
            lines.append(NO_RECORDING_MARKER)
        blocks.append("\n".join(lines))

    return "\n\n".join(blocks) + "\n"


def write_setlist(title: str, results: list[dict], path: str) -> str:
    """Write the set list to ``path`` (creating parent directories) and return the path."""
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        f.write(build_setlist(title, results))

    return path
