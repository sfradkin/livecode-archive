import ftplib
import logging
import os
import ssl
import time
from collections.abc import Callable
from typing import Any

from tqdm import tqdm

from utils.backupcommon import BackupSummary, local_files

BLOCK_SIZE = 1024 * 1024  # 1 MB
MAX_ATTEMPTS = 3
PART_SUFFIX = ".part"
DEFAULT_FILE_MODE = 0o644  # rw-r--r--
DEFAULT_DIR_MODE = 0o755  # rwxr-xr-x


class FtpBackup:
    """Pushes the files in a local directory to a remote FTP directory over FTPS.

    Files are uploaded under a temporary ``.part`` name and renamed once the remote size matches, so a file under
    its final name is always complete. Re-runs therefore skip any file whose remote size equals the local size.

    Uploaded files get ``file_mode`` and newly created directories get ``dir_mode`` via ``SITE CHMOD``. Skipped files
    are chmod-ed too, so a re-run also repairs the permissions of files from an earlier run.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        remote_dir: str,
        port: int = 21,
        tls: bool = True,
        timeout: int = 60,
        retry_delay: float = 2.0,
        file_mode: int = DEFAULT_FILE_MODE,
        dir_mode: int = DEFAULT_DIR_MODE,
        ftp_factory: Callable[..., Any] | None = None,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.remote_dir = remote_dir
        self.port = port
        # tls is only ever False in tests that talk to a plain local server
        self.tls = tls
        self.timeout = timeout
        self.retry_delay = retry_delay
        self.file_mode = file_mode
        self.dir_mode = dir_mode
        self._ftp_factory = ftp_factory or self._default_factory

    def _default_factory(self, host: str, port: int, timeout: int) -> Any:
        if self.tls:
            # certificate and hostname verification stay on; there is no fallback to plain FTP
            ftp: ftplib.FTP = ftplib.FTP_TLS(context=ssl.create_default_context())
        else:
            ftp = ftplib.FTP()
        ftp.connect(host, port, timeout=timeout)
        return ftp

    def _connect(self, create_dir: bool) -> tuple[Any, bool]:
        """Connect, log in and change to the remote dir. Returns (ftp, remote_dir_exists)."""
        ftp = self._ftp_factory(self.host, self.port, self.timeout)
        try:
            ftp.login(self.username, self.password)
            if self.tls:
                ftp.prot_p()  # encrypt the data channel too, not just the control channel
            exists = self._enter_remote_dir(ftp, create_dir)
        except BaseException:
            self._close(ftp)
            raise
        return ftp, exists

    def _enter_remote_dir(self, ftp: Any, create: bool) -> bool:
        if self.remote_dir.startswith("/"):
            ftp.cwd("/")
        for part in (p for p in self.remote_dir.split("/") if p):
            try:
                ftp.cwd(part)
            except ftplib.error_perm:
                if not create:
                    return False
                ftp.mkd(part)
                self._chmod(ftp, part, self.dir_mode)
                ftp.cwd(part)
        return True

    @staticmethod
    def _chmod(ftp: Any, name: str, mode: int) -> None:
        ftp.voidcmd(f"SITE CHMOD {mode:o} {name}")

    @staticmethod
    def _close(ftp: Any) -> None:
        try:
            ftp.quit()
        except Exception:
            try:
                ftp.close()
            except Exception:
                pass

    @staticmethod
    def _remote_sizes(ftp: Any) -> dict[str, int]:
        """Map of file name to size for the current remote directory."""
        ftp.voidcmd("TYPE I")  # SIZE is only reliable in binary mode
        try:
            return {
                name: int(facts["size"])
                for name, facts in ftp.mlsd(facts=["type", "size"])
                if facts.get("type") == "file" and "size" in facts
            }
        except ftplib.error_perm:
            pass  # server has no MLSD, fall back to NLST + SIZE

        try:
            names = ftp.nlst()
        except ftplib.error_perm:  # some servers answer 550 for an empty directory
            return {}

        sizes: dict[str, int] = {}
        for name in names:
            try:
                size = ftp.size(name)
            except ftplib.error_perm:
                continue  # not a regular file
            if size is not None:
                sizes[name] = size
        return sizes

    def _upload_file(self, ftp: Any, local_path: str) -> None:
        name = os.path.basename(local_path)
        part_name = name + PART_SUFFIX
        local_size = os.path.getsize(local_path)

        with (
            open(local_path, "rb") as f,
            tqdm(total=local_size, unit="B", unit_scale=True, desc=name[:40], disable=None) as bar,
        ):
            ftp.storbinary(f"STOR {part_name}", f, BLOCK_SIZE, callback=lambda block: bar.update(len(block)))

        remote_size = ftp.size(part_name)
        if remote_size != local_size:
            raise ftplib.Error(f"size mismatch for {name}: local {local_size}, remote {remote_size}")

        try:
            ftp.rename(part_name, name)
        except ftplib.error_perm:
            # some servers refuse to rename over an existing (stale, different-size) file
            ftp.delete(name)
            ftp.rename(part_name, name)

    def upload_dir(self, local_dir: str, dry_run: bool = False) -> BackupSummary:
        """Upload every regular, non-hidden file in ``local_dir`` (not recursive)."""
        summary = BackupSummary()
        names = local_files(local_dir)

        # connect first so bad credentials or certificates fail before any work; dry runs never create directories
        ftp, dir_exists = self._connect(create_dir=not dry_run)
        try:
            remote_sizes = self._remote_sizes(ftp) if dir_exists else {}
            for name in names:
                path = os.path.join(local_dir, name)
                if remote_sizes.get(name) == os.path.getsize(path):
                    summary.skipped.append(name)
                    if not dry_run:
                        ftp = self._chmod_with_retries(ftp, name, summary)
                    continue
                if dry_run:
                    summary.would_upload.append(name)
                    continue
                ftp = self._upload_with_retries(ftp, path, summary)
                if name in summary.uploaded:
                    ftp = self._chmod_with_retries(ftp, name, summary)
        finally:
            if ftp is not None:
                self._close(ftp)

        return summary

    def _upload_with_retries(self, ftp: Any, path: str, summary: BackupSummary) -> Any:
        """Upload one file, reconnecting after errors. Returns the (possibly new, possibly None) connection."""
        name = os.path.basename(path)
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if ftp is None:
                    ftp, _ = self._connect(create_dir=True)
                self._upload_file(ftp, path)
                summary.uploaded.append(name)
                return ftp
            except ftplib.all_errors as e:
                logging.warning(f"upload of {name} failed (attempt {attempt}/{MAX_ATTEMPTS}): {e}")
                if ftp is not None:
                    self._close(ftp)
                    ftp = None
                if attempt < MAX_ATTEMPTS:
                    time.sleep(self.retry_delay)

        summary.failed.append(name)
        return ftp

    def _chmod_with_retries(self, ftp: Any, name: str, summary: BackupSummary) -> Any:
        """Set the file mode on a file that is on the server. Failure is recorded, not silently ignored."""
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                if ftp is None:
                    ftp, _ = self._connect(create_dir=True)
                self._chmod(ftp, name, self.file_mode)
                return ftp
            except ftplib.error_perm as e:
                # the server answered and refused (e.g. 500/502 SITE CHMOD unsupported): retrying will not help
                logging.warning(f"could not set permissions on {name}: {e}")
                break
            except ftplib.all_errors as e:
                logging.warning(f"chmod of {name} failed (attempt {attempt}/{MAX_ATTEMPTS}): {e}")
                if ftp is not None:
                    self._close(ftp)
                    ftp = None
                if attempt < MAX_ATTEMPTS:
                    time.sleep(self.retry_delay)

        summary.chmod_failed.append(name)
        return ftp
