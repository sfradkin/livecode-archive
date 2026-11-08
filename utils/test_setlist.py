import importlib.util
import json
import os
import subprocess
from pathlib import Path

from utils.setlist import (
    NO_RECORDING_MARKER,
    build_archive_id,
    build_setlist,
    predict_archive_ids,
    write_setlist,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _result(name: str, starts_at: str, recordings: list[str] | None = None, **overrides) -> dict:
    result = {
        "publisher_name": name,
        "title": f"{name} set",
        "description": f"{name} description",
        "recordings": ["file.flv"] if recordings is None else recordings,
        "starts_at": starts_at,
    }
    result.update(overrides)
    return result


def test_title_is_first_line():
    text = build_setlist("My Stream", [_result("a", "2026-11-06T07:00:00Z")])
    assert text.splitlines()[0] == "My Stream"


def test_sets_are_in_chronological_order():
    results = [
        _result("late", "2026-11-06T09:00:00Z"),
        _result("early", "2026-11-06T07:00:00Z"),
        _result("middle", "2026-11-06T08:00:00Z"),
    ]
    text = build_setlist("T", results)
    assert text.index("Artist: early") < text.index("Artist: middle") < text.index("Artist: late")


def test_ties_keep_metadata_order():
    results = [_result("first", "2026-11-06T07:00:00Z"), _result("second", "2026-11-06T07:00:00Z")]
    text = build_setlist("T", results)
    assert text.index("Artist: first") < text.index("Artist: second")


def test_start_time_is_reported_in_utc():
    results = [_result("a", "2026-11-06T09:30:00+02:00")]
    assert "2026-11-06 07:30 UTC" in build_setlist("T", results)


def test_offset_times_sort_by_actual_instant():
    # 07:30 UTC is earlier than 08:00 UTC even though the local clock reads later
    results = [_result("utc", "2026-11-06T08:00:00Z"), _result("offset", "2026-11-06T09:30:00+02:00")]
    text = build_setlist("T", results)
    assert text.index("Artist: offset") < text.index("Artist: utc")


def test_entry_block_fields():
    text = build_setlist("T", [_result("Artist X", "2026-11-06T07:00:00Z", title="Set Y", description="Hello")])
    assert "2026-11-06 07:00 UTC\nArtist: Artist X\nTitle: Set Y\nDescription: Hello\n" in text
    assert NO_RECORDING_MARKER not in text


def test_no_recording_marker_only_for_sets_without_recordings():
    results = [
        _result("recorded", "2026-11-06T07:00:00Z"),
        _result("missing", "2026-11-06T08:00:00Z", recordings=[]),
    ]
    blocks = build_setlist("T", results).split("\n\n")
    assert NO_RECORDING_MARKER not in blocks[1]
    assert NO_RECORDING_MARKER in blocks[2]


def test_description_newlines_normalized_and_preserved():
    results = [_result("a", "2026-11-06T07:00:00Z", description="  line one\r\n\r\nline two\r\n")]
    text = build_setlist("T", results)
    assert "Description: line one\n\nline two\n" in text
    assert "\r" not in text


def test_missing_description_is_empty():
    results = [_result("a", "2026-11-06T07:00:00Z", description=None)]
    assert "Description: \n" in build_setlist("T", results)


def test_write_setlist_creates_parent_dirs_and_writes_utf8(tmp_path):
    path = str(tmp_path / "nested" / "dir" / "out.txt")
    result = write_setlist("Stream", [_result("Álex Cárdenas ♪", "2026-11-06T07:00:00Z")], path)
    assert result == path
    with open(path, encoding="utf-8") as f:
        assert "Artist: Álex Cárdenas ♪" in f.read()


def _load_cli():
    spec = importlib.util.spec_from_file_location("generate_setlist", REPO_ROOT / "generate-setlist.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_generates_setlist_from_metadata_file(tmp_path):
    metadata = {"count": 2, "results": [_result("b", "2026-11-06T08:00:00Z"), _result("a", "2026-11-06T07:00:00Z")]}
    metadata_file = tmp_path / "meta.json"
    metadata_file.write_text(json.dumps(metadata), encoding="utf-8")
    output = tmp_path / "out" / "setlist.txt"

    path = _load_cli().main([str(metadata_file), "--title", "CLI Stream", "--output", str(output)])

    assert path == str(output)
    text = output.read_text(encoding="utf-8")
    assert text.startswith("CLI Stream\n")
    assert text.index("Artist: a") < text.index("Artist: b")


def test_cli_default_output_path_is_gitignored():
    default_output = os.path.join(_load_cli().DEFAULT_OUTPUT_DIR, "some-metadata-setlist.txt")
    check = subprocess.run(["git", "check-ignore", "-q", default_output], cwd=REPO_ROOT)
    assert check.returncode == 0


def test_build_archive_id_matches_existing_slug_rules():
    assert build_archive_id("Álex Cárdenas & Friends!", "pre-") == "pre-alex-cardenas---friends-"
    assert build_archive_id("_\\|/_", "pre-") == "pre------"
    assert build_archive_id("TOPLAP", "pre-", pub_inc=1) == "pre-toplap"
    assert build_archive_id("TOPLAP", "pre-", pub_inc=3) == "pre-toplap-3"


def test_setlist_includes_archive_url_when_id_known():
    results = [_result("a", "2026-11-06T07:00:00Z", url="https://muxy/1/")]
    text = build_setlist("T", results, {"https://muxy/1/": "pre-a"})
    assert "Archive: https://archive.org/details/pre-a\n" in text


def test_setlist_omits_archive_url_when_not_archived():
    results = [
        _result("a", "2026-11-06T07:00:00Z", url="https://muxy/1/"),
        _result("b", "2026-11-06T08:00:00Z", url="https://muxy/2/", recordings=[]),
    ]
    assert "Archive:" not in build_setlist("T", results)
    text = build_setlist("T", results, {"https://muxy/1/": "pre-a"})
    assert text.count("Archive:") == 1
    blocks = text.split("\n\n")
    assert "Archive:" in blocks[1] and "Archive:" not in blocks[2]


def test_archive_line_comes_before_no_recording_marker_and_after_description():
    results = [_result("a", "2026-11-06T07:00:00Z", url="https://muxy/1/")]
    block = build_setlist("T", results, {"https://muxy/1/": "pre-a"}).split("\n\n")[1]
    assert block.splitlines()[-1] == "Archive: https://archive.org/details/pre-a"


def test_predict_archive_ids_numbers_repeat_publishers_in_metadata_order():
    results = [
        _result("Dup", "2026-11-06T09:00:00Z", url="u1"),
        _result("Other", "2026-11-06T07:00:00Z", url="u2"),
        _result("Dup", "2026-11-06T08:00:00Z", url="u3"),
        _result("Dup", "2026-11-06T10:00:00Z", url="u4", recordings=[]),
        _result("Dup", "2026-11-06T11:00:00Z", url="u5"),
    ]
    ids = predict_archive_ids(results, "p-")
    assert ids == {"u1": "p-dup", "u2": "p-other", "u3": "p-dup-2", "u5": "p-dup-4"}


def test_cli_with_archive_id_prefix_adds_urls(tmp_path):
    metadata = {"results": [_result("Solo", "2026-11-06T07:00:00Z", url="u1")]}
    metadata_file = tmp_path / "meta.json"
    metadata_file.write_text(json.dumps(metadata), encoding="utf-8")
    output = tmp_path / "setlist.txt"

    _load_cli().main([str(metadata_file), "--title", "T", "--output", str(output), "--archive-id-prefix", "p-"])

    assert "Archive: https://archive.org/details/p-solo" in output.read_text(encoding="utf-8")


def test_predict_archive_ids_treats_names_differing_in_case_or_punctuation_as_same_publisher():
    results = [
        _result("Kretopi", "2026-11-06T08:00:00Z", url="u1"),
        _result("kretopi", "2026-11-06T09:00:00Z", url="u2"),
        _result("claro F!x", "2026-11-06T10:00:00Z", url="u3"),
        _result("claro F-x", "2026-11-06T11:00:00Z", url="u4"),
    ]
    ids = predict_archive_ids(results, "p-")
    assert ids == {"u1": "p-kretopi", "u2": "p-kretopi-2", "u3": "p-claro-f-x", "u4": "p-claro-f-x-2"}
    assert len(set(ids.values())) == len(ids)
