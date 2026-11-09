import importlib.util
from pathlib import Path
from typing import Any

import boto3
import botocore.exceptions
import pytest
from boto3.exceptions import S3UploadFailedError
from moto import mock_aws

from utils import s3backup
from utils.s3backup import MAX_ATTEMPTS, S3Backup, S3BackupError

BUCKET = "test-bucket"
REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def fake_aws(monkeypatch):
    """Never let a test see real credentials or profiles; moto serves everything locally."""
    for var in ("AWS_PROFILE", "AWS_SESSION_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-2")
    monkeypatch.setenv("AWS_CONFIG_FILE", "/nonexistent")
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", "/nonexistent")


@pytest.fixture
def s3():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-2")
        client.create_bucket(Bucket=BUCKET, CreateBucketConfiguration={"LocationConstraint": "us-east-2"})
        yield client


def _backup(client, prefix="stream-2026", **kwargs) -> S3Backup:
    return S3Backup(BUCKET, prefix, client=client, retry_delay=0, **kwargs)


def _make_files(tmp_path: Path, files: dict[str, bytes]) -> Path:
    for name, data in files.items():
        (tmp_path / name).write_bytes(data)
    return tmp_path


def _keys(client, prefix="") -> dict[str, int]:
    resp = client.list_objects_v2(Bucket=BUCKET, Prefix=prefix)
    return {o["Key"]: o["Size"] for o in resp.get("Contents", [])}


class Flaky:
    """Wraps a real client; the first ``failures`` upload_file calls raise ``error``."""

    def __init__(self, client, failures: int, error: Exception, only: str | None = None):
        self._client = client
        self.failures = failures
        self.error = error
        self.only = only
        self.calls: list[str] = []

    def upload_file(self, filename, bucket, key, **kwargs):
        self.calls.append(key)
        if (self.only is None or key.endswith(self.only)) and self.failures > 0:
            self.failures -= 1
            raise self.error
        return self._client.upload_file(filename, bucket, key, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


# --- uploads -----------------------------------------------------------------------------------------------


def test_uploads_files_under_prefix_with_content_and_storage_class(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha" * 100, "b.flv": b"beta"})

    summary = _backup(s3).upload_dir(str(src))

    assert sorted(summary.uploaded) == ["a.flv", "b.flv"]
    assert not summary.failed and not summary.skipped
    assert s3.get_object(Bucket=BUCKET, Key="stream-2026/a.flv")["Body"].read() == b"alpha" * 100
    assert s3.head_object(Bucket=BUCKET, Key="stream-2026/b.flv")["StorageClass"] == "INTELLIGENT_TIERING"


def test_storage_class_is_configurable(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"x"})
    _backup(s3, storage_class="STANDARD_IA").upload_dir(str(src))
    assert s3.head_object(Bucket=BUCKET, Key="stream-2026/a.flv")["StorageClass"] == "STANDARD_IA"


def test_prefix_slashes_are_normalised(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"x"})
    _backup(s3, prefix="/stream-2026/").upload_dir(str(src))
    assert list(_keys(s3)) == ["stream-2026/a.flv"]


def test_second_run_skips_everything(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha", "b.flv": b"beta"})
    _backup(s3).upload_dir(str(src))

    summary = _backup(s3).upload_dir(str(src))

    assert sorted(summary.skipped) == ["a.flv", "b.flv"]
    assert not summary.uploaded


def test_remote_object_with_different_size_is_replaced(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"complete contents"})
    s3.put_object(Bucket=BUCKET, Key="stream-2026/a.flv", Body=b"trunc")

    summary = _backup(s3).upload_dir(str(src))

    assert summary.uploaded == ["a.flv"]
    assert s3.get_object(Bucket=BUCKET, Key="stream-2026/a.flv")["Body"].read() == b"complete contents"


def test_hidden_files_and_subdirectories_are_ignored(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"x", ".DS_Store": b"junk"})
    (src / "nested").mkdir()
    (src / "nested" / "c.flv").write_bytes(b"nested")

    summary = _backup(s3).upload_dir(str(src))

    assert summary.uploaded == ["a.flv"]
    assert list(_keys(s3)) == ["stream-2026/a.flv"]


def test_folder_marker_and_deeper_keys_do_not_count_as_files(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"x"})
    s3.put_object(Bucket=BUCKET, Key="stream-2026/", Body=b"")
    s3.put_object(Bucket=BUCKET, Key="stream-2026/sub/a.flv", Body=b"x")

    summary = _backup(s3).upload_dir(str(src))

    assert summary.uploaded == ["a.flv"]  # the nested object of the same name is a different key


def test_other_prefixes_are_untouched(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"new"})
    s3.put_object(Bucket=BUCKET, Key="other-stream/a.flv", Body=b"old")

    _backup(s3).upload_dir(str(src))

    assert s3.get_object(Bucket=BUCKET, Key="other-stream/a.flv")["Body"].read() == b"old"


def test_prefix_that_is_a_string_prefix_of_another_folder_is_not_confused(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"x"})
    s3.put_object(Bucket=BUCKET, Key="stream-2026-extra/a.flv", Body=b"x")

    summary = _backup(s3).upload_dir(str(src))

    assert summary.uploaded == ["a.flv"]


def test_dry_run_writes_nothing(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha", "b.flv": b"beta"})
    s3.put_object(Bucket=BUCKET, Key="stream-2026/b.flv", Body=b"beta")

    summary = _backup(s3).upload_dir(str(src), dry_run=True)

    assert summary.would_upload == ["a.flv"]
    assert summary.skipped == ["b.flv"]
    assert not summary.uploaded
    assert list(_keys(s3)) == ["stream-2026/b.flv"]


def test_more_than_one_page_of_existing_keys_is_seen(s3, tmp_path):
    names = {f"f{i:04d}.flv": b"x" for i in range(1005)}
    src = _make_files(tmp_path, names)
    for name in names:
        s3.put_object(Bucket=BUCKET, Key=f"stream-2026/{name}", Body=b"x")

    summary = _backup(s3).upload_dir(str(src), dry_run=True)

    assert len(summary.skipped) == 1005
    assert not summary.would_upload


def test_large_file_uses_multipart_and_round_trips(s3, tmp_path):
    data = bytes(range(256)) * 80_000  # ~20 MB
    src = _make_files(tmp_path, {"big.flv": data})

    summary = _backup(s3, chunk_size=5 * 1024 * 1024).upload_dir(str(src))

    assert summary.uploaded == ["big.flv"]
    assert s3.get_object(Bucket=BUCKET, Key="stream-2026/big.flv")["Body"].read() == data


# --- retries and failures ------------------------------------------------------------------------------------


def test_transient_error_is_retried_then_succeeds(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha"})
    flaky = Flaky(s3, failures=2, error=botocore.exceptions.EndpointConnectionError(endpoint_url="http://x"))

    summary = _backup(flaky).upload_dir(str(src))

    assert summary.uploaded == ["a.flv"]
    assert len(flaky.calls) == 3
    assert _keys(s3) == {"stream-2026/a.flv": 5}


def test_file_fails_after_max_attempts_and_the_rest_continue(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha", "b.flv": b"beta"})
    flaky = Flaky(s3, failures=99, error=S3UploadFailedError("flaky network"), only="a.flv")

    summary = _backup(flaky).upload_dir(str(src))

    assert summary.failed == ["a.flv"]
    assert summary.uploaded == ["b.flv"]
    assert flaky.calls.count("stream-2026/a.flv") == MAX_ATTEMPTS


def test_size_mismatch_after_upload_counts_as_a_failed_attempt(s3, tmp_path, monkeypatch):
    src = _make_files(tmp_path, {"a.flv": b"alpha"})
    real_head = s3.head_object

    class WrongSize(Flaky):
        def head_object(self, **kwargs):
            return {**real_head(**kwargs), "ContentLength": 1}

    summary = _backup(WrongSize(s3, 0, RuntimeError())).upload_dir(str(src))

    assert summary.failed == ["a.flv"]


def test_access_denied_on_upload_aborts_without_retrying_every_file(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha", "b.flv": b"beta"})
    denied = S3UploadFailedError("Failed to upload: An error occurred (AccessDenied) when calling PutObject")
    flaky = Flaky(s3, failures=99, error=denied)

    with pytest.raises(S3BackupError, match="refused"):
        _backup(flaky).upload_dir(str(src))

    assert len(flaky.calls) == 1


def test_missing_bucket_is_reported_before_any_upload(tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha"})
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-2")  # bucket never created
        with pytest.raises(S3BackupError, match="NoSuchBucket"):
            _backup(client).upload_dir(str(src))


def test_missing_credentials_are_reported_before_any_upload(tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha"})

    class NoCreds:
        def get_paginator(self, name):
            raise botocore.exceptions.NoCredentialsError()

    with pytest.raises(S3BackupError, match="credentials"):
        _backup(NoCreds()).upload_dir(str(src))


def test_make_client_uses_the_named_profile_and_region(monkeypatch):
    seen = {}

    class FakeSession:
        def __init__(self, profile_name=None, region_name=None):
            seen.update(profile=profile_name, region=region_name)

        def client(self, name):
            return f"{name}-client"

    monkeypatch.setattr(s3backup.boto3.session, "Session", FakeSession)

    assert s3backup.make_client("backups", "us-east-2") == "s3-client"
    assert seen == {"profile": "backups", "region": "us-east-2"}


# --- CLI -----------------------------------------------------------------------------------------------------


def _load_cli():
    spec = importlib.util.spec_from_file_location("backup_to_s3", REPO_ROOT / "backup-to-s3.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_cli_default_bucket_is_the_live_coding_bucket():
    assert _load_cli().DEFAULT_BUCKET == "live-coding-42406474-571c-402b-a18c-3d42d1e32c9a"


def test_cli_uploads_then_skips(s3, tmp_path, capsys):
    cli = _load_cli()
    src = _make_files(tmp_path, {"a.flv": b"alpha", "b.flv": b"beta"})
    argv = [str(src), "around-the-world-nov-2026", "--bucket", BUCKET]

    assert cli.main(argv, client=s3) == 0
    assert "uploaded 2, skipped 0, failed 0" in capsys.readouterr().out
    assert set(_keys(s3)) == {"around-the-world-nov-2026/a.flv", "around-the-world-nov-2026/b.flv"}

    assert cli.main(argv, client=s3) == 0
    assert "uploaded 0, skipped 2, failed 0" in capsys.readouterr().out


def test_cli_dry_run_lists_files_and_uploads_nothing(s3, tmp_path, capsys):
    src = _make_files(tmp_path, {"a.flv": b"alpha"})

    assert _load_cli().main([str(src), "s", "--bucket", BUCKET, "--dry-run"], client=s3) == 0

    out = capsys.readouterr().out
    assert "dry run: 1 to upload, 0 already present" in out
    assert "would upload: a.flv" in out
    assert not _keys(s3)


def test_cli_passes_storage_class(s3, tmp_path):
    src = _make_files(tmp_path, {"a.flv": b"alpha"})
    _load_cli().main([str(src), "s", "--bucket", BUCKET, "--storage-class", "ONEZONE_IA"], client=s3)
    assert s3.head_object(Bucket=BUCKET, Key="s/a.flv")["StorageClass"] == "ONEZONE_IA"


@pytest.mark.parametrize("bad", ["", "  ", "/abs", "..", "a/../b", "."])
def test_cli_rejects_bad_subdirectories_before_touching_s3(bad, tmp_path, capsys):
    class Boom:
        def __getattr__(self, name):
            raise AssertionError("S3 must not be touched")

    with pytest.raises(SystemExit) as exc:
        _load_cli().main([str(tmp_path), bad], client=Boom())

    assert exc.value.code == 2
    assert "invalid subdirectory" in capsys.readouterr().err


def test_cli_exit_code_is_1_when_a_file_fails(s3, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(s3backup.time, "sleep", lambda s: None)
    src = _make_files(tmp_path, {"a.flv": b"alpha"})
    flaky = Flaky(s3, failures=99, error=S3UploadFailedError("flaky"))

    assert _load_cli().main([str(src), "s", "--bucket", BUCKET], client=flaky) == 1
    assert "FAILED: a.flv" in capsys.readouterr().err


def test_cli_exit_code_is_2_for_a_missing_bucket(tmp_path, capsys):
    src = _make_files(tmp_path, {"a.flv": b"alpha"})
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-2")
        assert _load_cli().main([str(src), "s", "--bucket", "nope"], client=client) == 2
    assert "S3 backup stopped" in capsys.readouterr().err
