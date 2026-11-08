import ftplib
import importlib.util
import ssl
import stat
import threading
from pathlib import Path
from typing import Any

import pytest
from pyftpdlib.authorizers import DummyAuthorizer
from pyftpdlib.handlers import FTPHandler
from pyftpdlib.servers import FTPServer

from utils.ftpbackup import MAX_ATTEMPTS, PART_SUFFIX, FtpBackup

REPO_ROOT = Path(__file__).resolve().parent.parent
REMOTE_DIR = "public-html/live coding/stream"


# ---------------------------------------------------------------- in-memory fake FTP server


class FakeServer:
    """Shared state for FakeFTP connections, so data survives a reconnect."""

    def __init__(self) -> None:
        self.dirs: set[tuple[str, ...]] = {()}
        self.files: dict[tuple[str, ...], dict[str, bytes]] = {}
        self.stor_calls: list[str] = []
        self.rename_calls: list[tuple[str, str]] = []
        self.connections = 0
        self.fail_next_stors = 0  # raise a dropped-connection error for this many STOR calls
        self.fail_stors_for: set[str] = set()  # always fail STOR for these (final) names
        self.supports_mlsd = True
        self.modes: dict[tuple[str, ...], int] = {}  # (dir parts..., name) -> mode set via SITE CHMOD
        self.chmod_unsupported = False  # answer SITE CHMOD with 500 for everything
        self.chmod_fails_for: set[str] = set()  # answer SITE CHMOD with 550 for these names

    def put(self, remote_dir: tuple[str, ...], name: str, data: bytes) -> None:
        for i in range(len(remote_dir) + 1):
            self.dirs.add(remote_dir[:i])
        self.files.setdefault(remote_dir, {})[name] = data


class FakeFTP:
    def __init__(self, server: FakeServer) -> None:
        self.server = server
        self.cwd_parts: tuple[str, ...] = ()
        self.logged_in = False
        self.prot_p_called = False
        server.connections += 1

    def login(self, user: str, password: str) -> None:
        self.logged_in = True

    def prot_p(self) -> None:
        self.prot_p_called = True

    def cwd(self, part: str) -> None:
        if part == "/":
            self.cwd_parts = ()
            return
        target = (*self.cwd_parts, part)
        if target not in self.server.dirs:
            raise ftplib.error_perm("550 no such directory")
        self.cwd_parts = target

    def mkd(self, part: str) -> None:
        self.server.dirs.add((*self.cwd_parts, part))

    def voidcmd(self, cmd: str) -> str:
        if cmd.startswith("SITE CHMOD "):
            _, _, mode, name = cmd.split(" ", 3)
            if self.server.chmod_unsupported:
                raise ftplib.error_perm("500 SITE CHMOD not understood")
            if name in self.server.chmod_fails_for:
                raise ftplib.error_perm("550 permission denied")
            self.server.modes[(*self.cwd_parts, name)] = int(mode, 8)
        return "200 ok"

    def _files(self) -> dict[str, bytes]:
        return self.server.files.setdefault(self.cwd_parts, {})

    def mlsd(self, facts: list[str]) -> list[tuple[str, dict[str, str]]]:
        if not self.server.supports_mlsd:
            raise ftplib.error_perm("500 MLSD not understood")
        return [(n, {"type": "file", "size": str(len(d))}) for n, d in self._files().items()]

    def nlst(self) -> list[str]:
        return list(self._files())

    def size(self, name: str) -> int | None:
        if name not in self._files():
            raise ftplib.error_perm("550 no such file")
        return len(self._files()[name])

    def storbinary(self, cmd: str, fp: Any, blocksize: int, callback: Any = None) -> None:
        name = cmd.removeprefix("STOR ")
        self.server.stor_calls.append(name)
        final_name = name.removesuffix(PART_SUFFIX)
        if self.server.fail_next_stors > 0:
            self.server.fail_next_stors -= 1
            self._files()[name] = fp.read(5)  # leave a truncated partial behind
            raise ConnectionResetError("connection dropped")
        if final_name in self.server.fail_stors_for:
            raise ConnectionResetError("connection dropped")
        data = b""
        while block := fp.read(blocksize):
            data += block
            if callback:
                callback(block)
        self._files()[name] = data

    def rename(self, src: str, dst: str) -> None:
        self.server.rename_calls.append((src, dst))
        files = self._files()
        files[dst] = files.pop(src)

    def delete(self, name: str) -> None:
        self._files().pop(name, None)

    def quit(self) -> None:
        pass

    def close(self) -> None:
        pass


def _backup(server: FakeServer, **kwargs: Any) -> FtpBackup:
    kwargs.setdefault("tls", False)
    kwargs.setdefault("retry_delay", 0)
    return FtpBackup(
        "host", "user", "pw", REMOTE_DIR, ftp_factory=lambda host, port, timeout: FakeFTP(server), **kwargs
    )


@pytest.fixture
def local_dir(tmp_path: Path) -> Path:
    d = tmp_path / "recordings"
    d.mkdir()
    (d / "a.flv").write_bytes(b"aaaa")
    (d / "b.flv").write_bytes(b"bbbbbb")
    return d


REMOTE = ("public-html", "live coding", "stream")


# ---------------------------------------------------------------- unit tests (fake FTP)


def test_uploads_new_files_and_creates_remote_dirs(local_dir):
    server = FakeServer()
    summary = _backup(server).upload_dir(str(local_dir))

    assert summary.uploaded == ["a.flv", "b.flv"]
    assert summary.skipped == [] and summary.failed == []
    assert server.files[REMOTE] == {"a.flv": b"aaaa", "b.flv": b"bbbbbb"}


def test_uploads_go_to_part_name_then_rename(local_dir):
    server = FakeServer()
    _backup(server).upload_dir(str(local_dir))

    assert server.stor_calls == ["a.flv.part", "b.flv.part"]
    assert server.rename_calls == [("a.flv.part", "a.flv"), ("b.flv.part", "b.flv")]
    assert not any(n.endswith(PART_SUFFIX) for n in server.files[REMOTE])


def test_skips_files_with_matching_remote_size(local_dir):
    server = FakeServer()
    server.put(REMOTE, "a.flv", b"aaaa")
    summary = _backup(server).upload_dir(str(local_dir))

    assert summary.skipped == ["a.flv"]
    assert summary.uploaded == ["b.flv"]
    assert server.stor_calls == ["b.flv.part"]


def test_resends_files_whose_remote_size_differs(local_dir):
    server = FakeServer()
    server.put(REMOTE, "a.flv", b"aa")  # truncated earlier upload
    summary = _backup(server).upload_dir(str(local_dir))

    assert "a.flv" in summary.uploaded
    assert server.files[REMOTE]["a.flv"] == b"aaaa"


def test_falls_back_to_nlst_and_size_without_mlsd(local_dir):
    server = FakeServer()
    server.supports_mlsd = False
    server.put(REMOTE, "a.flv", b"aaaa")
    summary = _backup(server).upload_dir(str(local_dir))

    assert summary.skipped == ["a.flv"]
    assert summary.uploaded == ["b.flv"]


def test_retries_after_dropped_connection_then_succeeds(local_dir):
    server = FakeServer()
    server.fail_next_stors = 1
    summary = _backup(server).upload_dir(str(local_dir))

    assert summary.failed == []
    assert summary.uploaded == ["a.flv", "b.flv"]
    assert server.connections >= 2  # reconnected after the drop
    assert server.files[REMOTE]["a.flv"] == b"aaaa"


def test_records_failure_after_max_attempts_and_continues(local_dir):
    server = FakeServer()
    server.fail_stors_for = {"a.flv"}
    summary = _backup(server).upload_dir(str(local_dir))

    assert summary.failed == ["a.flv"]
    assert summary.uploaded == ["b.flv"]
    assert server.stor_calls.count("a.flv.part") == MAX_ATTEMPTS


def test_ignores_hidden_files_and_subdirectories(local_dir):
    (local_dir / ".DS_Store").write_bytes(b"x")
    (local_dir / "subdir").mkdir()
    (local_dir / "subdir" / "c.flv").write_bytes(b"c")
    server = FakeServer()
    summary = _backup(server).upload_dir(str(local_dir))

    assert summary.uploaded == ["a.flv", "b.flv"]


def test_dry_run_uploads_nothing_and_creates_nothing(local_dir):
    server = FakeServer()
    summary = _backup(server).upload_dir(str(local_dir), dry_run=True)

    assert summary.would_upload == ["a.flv", "b.flv"]
    assert summary.uploaded == []
    assert server.stor_calls == []
    assert server.dirs == {()}  # remote dirs were not created


def test_dry_run_reports_skips_for_existing_files(local_dir):
    server = FakeServer()
    server.put(REMOTE, "a.flv", b"aaaa")
    summary = _backup(server).upload_dir(str(local_dir), dry_run=True)

    assert summary.skipped == ["a.flv"]
    assert summary.would_upload == ["b.flv"]


def test_tls_connection_uses_prot_p(local_dir):
    server = FakeServer()
    created: list[FakeFTP] = []

    def factory(host: str, port: int, timeout: int) -> FakeFTP:
        created.append(FakeFTP(server))
        return created[-1]

    FtpBackup("host", "user", "pw", REMOTE_DIR, tls=True, ftp_factory=factory).upload_dir(str(local_dir))
    assert created[0].prot_p_called


def test_default_connection_is_verified_tls(monkeypatch):
    captured: dict[str, Any] = {}

    class RecordingFtpTls:
        def __init__(self, context: ssl.SSLContext) -> None:
            captured["context"] = context

        def connect(self, host: str, port: int, timeout: int) -> None:
            captured["connect"] = (host, port)

    monkeypatch.setattr(ftplib, "FTP_TLS", RecordingFtpTls)
    FtpBackup("ftp.example.com", "u", "p", "d")._default_factory("ftp.example.com", 21, 60)

    context = captured["context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert captured["connect"] == ("ftp.example.com", 21)


def test_uploaded_files_get_644_and_created_dirs_get_755(local_dir):
    server = FakeServer()
    _backup(server).upload_dir(str(local_dir))

    assert server.modes[(*REMOTE, "a.flv")] == 0o644
    assert server.modes[(*REMOTE, "b.flv")] == 0o644
    assert server.modes[("public-html",)] == 0o755
    assert server.modes[("public-html", "live coding")] == 0o755
    assert server.modes[REMOTE] == 0o755


def test_existing_directories_are_not_chmodded(local_dir):
    server = FakeServer()
    server.put(("public-html",), "index.html", b"x")  # public-html already exists
    _backup(server).upload_dir(str(local_dir))

    assert ("public-html",) not in server.modes
    assert server.modes[("public-html", "live coding")] == 0o755


def test_skipped_files_are_chmodded_too(local_dir):
    server = FakeServer()
    server.put(REMOTE, "a.flv", b"aaaa")
    summary = _backup(server).upload_dir(str(local_dir))

    assert summary.skipped == ["a.flv"]
    assert server.modes[(*REMOTE, "a.flv")] == 0o644


def test_custom_modes_are_applied(local_dir):
    server = FakeServer()
    _backup(server, file_mode=0o600, dir_mode=0o700).upload_dir(str(local_dir))

    assert server.modes[(*REMOTE, "a.flv")] == 0o600
    assert server.modes[REMOTE] == 0o700


def test_chmod_refused_for_a_file_is_recorded_not_ignored(local_dir):
    server = FakeServer()
    server.chmod_fails_for = {"a.flv"}
    summary = _backup(server).upload_dir(str(local_dir))

    assert summary.chmod_failed == ["a.flv"]
    assert "a.flv" in summary.uploaded  # the upload itself still counts
    assert (*REMOTE, "b.flv") in server.modes


def test_server_without_site_chmod_fails_before_uploading_anything(local_dir):
    server = FakeServer()
    server.chmod_unsupported = True
    with pytest.raises(ftplib.error_perm):
        _backup(server).upload_dir(str(local_dir))

    assert server.stor_calls == []


def test_dry_run_does_not_chmod(local_dir):
    server = FakeServer()
    server.put(REMOTE, "a.flv", b"aaaa")
    _backup(server).upload_dir(str(local_dir), dry_run=True)

    assert server.modes == {}


# ---------------------------------------------------------------- integration tests (pyftpdlib on localhost)


@pytest.fixture
def ftp_server(tmp_path: Path):
    home = tmp_path / "ftp-home"
    home.mkdir()
    authorizer = DummyAuthorizer()
    authorizer.add_user("user", "pw", str(home), perm="elradfmwMT")

    class Handler(FTPHandler):
        pass

    Handler.authorizer = authorizer
    server = FTPServer(("127.0.0.1", 0), Handler)
    stop = threading.Event()

    def run() -> None:
        # poll one step at a time so we can stop the loop before closing the sockets it is polling
        while not stop.is_set():
            server.ioloop.loop(timeout=0.05, blocking=False)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    try:
        yield home, server.address[1]
    finally:
        stop.set()
        thread.join(timeout=5)
        server.close_all()


def _real_backup(port: int, **kwargs: Any) -> FtpBackup:
    # tls=False only because the local test server has no certificate
    return FtpBackup("127.0.0.1", "user", "pw", REMOTE_DIR, port=port, tls=False, retry_delay=0, **kwargs)


def test_integration_uploads_byte_identical_files_into_nested_dir_with_space(local_dir, ftp_server):
    home, port = ftp_server
    big = bytes(range(256)) * 20000  # ~5 MB, spans several blocks
    (local_dir / "big.flv").write_bytes(big)

    summary = _real_backup(port).upload_dir(str(local_dir))

    dest = home / "public-html" / "live coding" / "stream"
    assert sorted(summary.uploaded) == ["a.flv", "b.flv", "big.flv"]
    assert (dest / "a.flv").read_bytes() == b"aaaa"
    assert (dest / "big.flv").read_bytes() == big
    assert not list(dest.glob("*.part"))


def test_integration_second_run_skips_everything(local_dir, ftp_server):
    _, port = ftp_server
    _real_backup(port).upload_dir(str(local_dir))
    summary = _real_backup(port).upload_dir(str(local_dir))

    assert summary.uploaded == []
    assert summary.skipped == ["a.flv", "b.flv"]


def test_integration_truncated_remote_file_is_replaced(local_dir, ftp_server):
    home, port = ftp_server
    dest = home / "public-html" / "live coding" / "stream"
    dest.mkdir(parents=True)
    (dest / "b.flv").write_bytes(b"bb")  # stale, wrong size

    summary = _real_backup(port).upload_dir(str(local_dir))

    assert "b.flv" in summary.uploaded
    assert (dest / "b.flv").read_bytes() == b"bbbbbb"


def test_integration_dry_run_changes_nothing(local_dir, ftp_server):
    home, port = ftp_server
    summary = _real_backup(port).upload_dir(str(local_dir), dry_run=True)

    assert summary.would_upload == ["a.flv", "b.flv"]
    assert list(home.iterdir()) == []


# ---------------------------------------------------------------- CLI


def _load_cli() -> Any:
    spec = importlib.util.spec_from_file_location("backup_to_ftp", REPO_ROOT / "backup-to-ftp.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _prompts(monkeypatch: pytest.MonkeyPatch, cli: Any) -> None:
    monkeypatch.setattr("builtins.input", lambda prompt="": "user")
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": "pw")


def test_cli_uploads_and_returns_zero(local_dir, ftp_server, monkeypatch, capsys):
    home, port = ftp_server
    cli = _load_cli()
    _prompts(monkeypatch, cli)

    code = cli.main([str(local_dir), "--host", "127.0.0.1", "--port", str(port), "--remote-dir", "out/dir"], tls=False)

    assert code == 0
    assert (home / "out" / "dir" / "a.flv").read_bytes() == b"aaaa"
    assert "uploaded 2, skipped 0, failed 0" in capsys.readouterr().out


def test_cli_dry_run_lists_files(local_dir, ftp_server, monkeypatch, capsys):
    home, port = ftp_server
    cli = _load_cli()
    _prompts(monkeypatch, cli)

    code = cli.main([str(local_dir), "--host", "127.0.0.1", "--port", str(port), "--dry-run"], tls=False)

    out = capsys.readouterr().out
    assert code == 0
    assert "would upload: a.flv" in out and "dry run: 2 to upload" in out
    assert list(home.iterdir()) == []


def test_cli_has_no_flag_to_disable_tls():
    cli = _load_cli()
    with pytest.raises(SystemExit):
        cli.main(["somedir", "--no-tls"])
    assert cli.DEFAULT_HOST == "ftp.fradkin.com"
    assert cli.DEFAULT_REMOTE_DIR == "public-html/live coding/around-the-world-nov-2026"


def test_integration_files_and_created_dirs_get_requested_permissions(local_dir, ftp_server):
    home, port = ftp_server
    _real_backup(port).upload_dir(str(local_dir))

    dest = home / "public-html" / "live coding" / "stream"
    assert stat.S_IMODE((dest / "a.flv").stat().st_mode) == 0o644
    assert stat.S_IMODE((dest / "b.flv").stat().st_mode) == 0o644
    for d in (home / "public-html", home / "public-html" / "live coding", dest):
        assert stat.S_IMODE(d.stat().st_mode) == 0o755


def test_integration_rerun_repairs_permissions_of_already_uploaded_files(local_dir, ftp_server):
    home, port = ftp_server
    _real_backup(port).upload_dir(str(local_dir))
    target = home / "public-html" / "live coding" / "stream" / "a.flv"
    target.chmod(0o600)

    summary = _real_backup(port).upload_dir(str(local_dir))

    assert summary.uploaded == []
    assert stat.S_IMODE(target.stat().st_mode) == 0o644


def test_cli_file_mode_flag(local_dir, ftp_server, monkeypatch):
    home, port = ftp_server
    cli = _load_cli()
    _prompts(monkeypatch, cli)

    code = cli.main(
        [str(local_dir), "--host", "127.0.0.1", "--port", str(port), "--remote-dir", "x", "--file-mode", "600"],
        tls=False,
    )

    assert code == 0
    assert stat.S_IMODE((home / "x" / "a.flv").stat().st_mode) == 0o600
