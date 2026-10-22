"""GitHub-Update-Logik: Versionen, Release-Pruefung, Download und Installation.

Die Logik ist bewusst frei von UI-Abhaengigkeiten und wird in Tests mit
einem austauschbaren ``opener`` (statt urllib) geprueft.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

from .paths import atomic_write_json
from .version import __version__

log = logging.getLogger(__name__)

REPO = "soendi/GaubenMaster2"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_BASE = f"https://github.com/{REPO}/releases/download/"
CHECKSUMS_NAME = "SHA256SUMS.txt"
INSTALLER_PREFIX = "GaubenMaster2-Setup-"
INSTALLER_SUFFIX = ".exe"

CHECK_INTERVAL = 6 * 60 * 60
MIN_INSTALLER_SIZE = 1 * 1024 * 1024
MAX_INSTALLER_SIZE = 200 * 1024 * 1024
MAX_API_BYTES = 1024 * 1024
MAX_CHECKSUMS_BYTES = 256 * 1024
USER_AGENT = f"GaubenMaster2/{__version__}"
ALLOWED_HOSTS = {
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
}

_VERSION_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")

Opener = Callable[..., Any]
Progress = Callable[[int, int], None]


class UpdateError(Exception):
    """Fehler mit einer fuer Endbenutzer verstaendlichen Meldung."""


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    tag: str
    notes: str
    installer_url: str
    installer_name: str
    installer_size: int
    checksums_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: Any) -> "UpdateInfo":
        if not isinstance(value, dict):
            raise ValueError("ungueltiger Cache")
        info = cls(
            version=str(value["version"]),
            tag=str(value["tag"]),
            notes=str(value.get("notes", "")),
            installer_url=str(value["installer_url"]),
            installer_name=str(value["installer_name"]),
            installer_size=int(value["installer_size"]),
            checksums_url=str(value["checksums_url"]),
        )
        parse_version(info.version)
        if not _VERSION_RE.match(info.version):
            raise ValueError("ungueltige Version")
        if info.installer_name != installer_filename(info.version):
            raise ValueError("ungueltiger Dateiname")
        if not MIN_INSTALLER_SIZE <= info.installer_size <= MAX_INSTALLER_SIZE:
            raise ValueError("ungueltige Dateigroesse")
        _validate_url(info.installer_url, info.tag, info.installer_name)
        _validate_url(info.checksums_url, info.tag, CHECKSUMS_NAME)
        return info


def parse_version(value: str) -> tuple[int, int, int]:
    text = value.strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    match = _VERSION_RE.match(text)
    if not match:
        raise ValueError(f"Ungueltige Versionsnummer: {value!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


def installer_filename(version: str) -> str:
    return f"{INSTALLER_PREFIX}{version}{INSTALLER_SUFFIX}"


def _validate_url(url: str, tag: str, asset_name: str) -> None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in ALLOWED_HOSTS:
        raise UpdateError("Der Release-Download stammt nicht von GitHub.")
    if host == "github.com":
        expected = f"/{REPO.lower()}/releases/download/{tag}/".lower()
        if not unquote(parsed.path).lower().startswith(expected):
            raise UpdateError("Der Release-Download passt nicht zum Repository.")
    if unquote(Path(parsed.path).name) != asset_name:
        raise UpdateError("Der Release-Dateiname ist unerwartet.")


def _open(
    opener: Opener,
    url: str,
    timeout: float,
    accept: str = "application/vnd.github+json",
) -> Any:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept})
    try:
        return opener(request, timeout=timeout)
    except HTTPError as exc:
        raise UpdateError(f"GitHub antwortete mit HTTP {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise UpdateError("GitHub ist nicht erreichbar.") from exc


def _read_limited(response: Any, limit: int) -> bytes:
    raw = response.read(limit + 1)
    if len(raw) > limit:
        raise UpdateError("Die Serverantwort ist unerwartet gross.")
    return raw


def _http_status(response: Any) -> int:
    return int(getattr(response, "status", 200) or 200)


def _release_assets(release: dict[str, Any], version: str) -> tuple[dict, dict]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise UpdateError("Der Release enthaelt keine Dateien.")
    installer_name = installer_filename(version)
    found: dict[str, dict] = {}
    for asset in assets:
        if not isinstance(asset, dict):
            continue
        name = asset.get("name")
        if name in (installer_name, CHECKSUMS_NAME) and name not in found:
            found[name] = asset
    for required in (installer_name, CHECKSUMS_NAME):
        if required not in found:
            raise UpdateError(f"Release-Datei fehlt: {required}")
    installer = found[installer_name]
    checksums = found[CHECKSUMS_NAME]
    for asset, expected_name in ((installer, installer_name), (checksums, CHECKSUMS_NAME)):
        try:
            size = int(asset.get("size", 0))
        except (TypeError, ValueError) as exc:
            raise UpdateError("Ungueltige Dateigroesse im Release.") from exc
        if expected_name == installer_name and not (
            MIN_INSTALLER_SIZE <= size <= MAX_INSTALLER_SIZE
        ):
            raise UpdateError("Der Installer hat eine unerwartete Dateigroesse.")
        if expected_name == CHECKSUMS_NAME and not 0 < size <= MAX_CHECKSUMS_BYTES:
            raise UpdateError("Die Pruefsummendatei hat eine unerwartete Groesse.")
        url = asset.get("browser_download_url")
        if not isinstance(url, str):
            raise UpdateError("Release-Download-Adresse fehlt.")
        _validate_url(url, release["tag_name"], expected_name)
    return installer, checksums


def fetch_latest_release(
    current_version: str = __version__,
    opener: Opener = urlopen,
    timeout: float = 10.0,
) -> UpdateInfo | None:
    """Ermittelt die neueste stabile Version. ``None`` = kein Update."""
    with _open(opener, API_URL, timeout) as response:
        if _http_status(response) != 200:
            raise UpdateError("GitHub lieferte keine gueltige Release-Antwort.")
        try:
            release = json.loads(_read_limited(response, MAX_API_BYTES))
        except (ValueError, UnicodeDecodeError) as exc:
            raise UpdateError("Die GitHub-Antwort ist unlesbar.") from exc

    if not isinstance(release, dict):
        raise UpdateError("Die GitHub-Antwort ist unerwartet.")
    if release.get("draft") or release.get("prerelease"):
        return None

    tag = release.get("tag_name")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise UpdateError("Der Release-Tag ist ungueltig.")
    version = tag[1:]
    try:
        parse_version(version)
    except ValueError as exc:
        raise UpdateError("Der Release-Tag ist ungueltig.") from exc
    if not is_newer(version, current_version):
        return None

    installer, checksums = _release_assets(release, version)
    notes = release.get("body")
    return UpdateInfo(
        version=version,
        tag=tag,
        notes=notes[:4000] if isinstance(notes, str) else "",
        installer_url=str(installer["browser_download_url"]),
        installer_name=installer_filename(version),
        installer_size=int(installer["size"]),
        checksums_url=str(checksums["browser_download_url"]),
    )


def parse_checksums(text: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2 or not _SHA256_RE.match(parts[0]):
            continue
        name = parts[1].lstrip("*")
        if name:
            result[name.lower()] = parts[0].lower()
    return result


def _download_checksums(info: UpdateInfo, opener: Opener, timeout: float) -> str:
    with _open(opener, info.checksums_url, timeout, accept="text/plain") as response:
        if _http_status(response) != 200:
            raise UpdateError("Pruefsummen konnten nicht geladen werden.")
        raw = _read_limited(response, MAX_CHECKSUMS_BYTES)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    expected = parse_checksums(text).get(info.installer_name.lower())
    if not expected:
        raise UpdateError("Fuer den Installer fehlt eine Pruefsumme.")
    return expected


def download_and_verify(
    info: UpdateInfo,
    target_dir: Path,
    opener: Opener = urlopen,
    progress: Progress | None = None,
    timeout: float = 30.0,
) -> Path:
    """Laedt den Installer, prueft Status, Groesse und SHA256, dann atomar ablegen."""
    _validate_url(info.installer_url, info.tag, info.installer_name)
    _validate_url(info.checksums_url, info.tag, CHECKSUMS_NAME)
    if info.installer_name != installer_filename(info.version):
        raise UpdateError("Der Release-Dateiname ist unerwartet.")

    target_dir.mkdir(parents=True, exist_ok=True)
    destination = target_dir / info.installer_name
    part = destination.with_name(destination.name + ".part")
    try:
        free = shutil.disk_usage(target_dir).free
    except OSError:
        free = 0
    if free and free < info.installer_size + 10 * 1024 * 1024:
        raise UpdateError("Zu wenig freier Speicherplatz fuer das Update.")

    digest = hashlib.sha256()
    size = 0
    total = info.installer_size
    if progress:
        progress(0, total)
    try:
        with _open(opener, info.installer_url, timeout, accept="application/octet-stream") as response:
            if _http_status(response) not in (200, 206):
                raise UpdateError("Der Installer-Download ist fehlgeschlagen.")
            headers = getattr(response, "headers", None)
            header_size = headers.get("Content-Length") if headers else None
            if header_size is not None:
                try:
                    declared = int(header_size)
                except (TypeError, ValueError) as exc:
                    raise UpdateError("Ungueltige Download-Groesse.") from exc
                if declared != info.installer_size:
                    raise UpdateError("Die Download-Groesse stimmt nicht mit dem Release ueberein.")
            with open(part, "wb") as handle:
                while True:
                    chunk = response.read(64 * 1024)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > info.installer_size:
                        raise UpdateError("Der Download ist groesser als angekuendigt.")
                    handle.write(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(size, total)
                handle.flush()
                os.fsync(handle.fileno())
        if size != info.installer_size:
            raise UpdateError("Der Download ist unvollstaendig.")
        if size < MIN_INSTALLER_SIZE:
            raise UpdateError("Der Download ist unerwartet klein.")
        expected = _download_checksums(info, opener, timeout)
        if not hmac.compare_digest(digest.hexdigest(), expected):
            raise UpdateError("Die Pruefsumme des Downloads stimmt nicht.")
        if progress:
            progress(size, total)
        os.replace(part, destination)
        log.info("Update %s heruntergeladen und verifiziert.", info.version)
        return destination
    except Exception:
        try:
            part.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def read_cache(path: Path) -> tuple[int, UpdateInfo | None]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        checked = int(value.get("checked_at", 0))
        raw_info = value.get("update")
        info = UpdateInfo.from_dict(raw_info) if raw_info else None
        return checked, info
    except (OSError, ValueError, TypeError, KeyError, UpdateError):
        return 0, None


def save_cache(path: Path, info: UpdateInfo | None, now: float | None = None) -> None:
    try:
        atomic_write_json(
            path,
            {
                "checked_at": int(now if now is not None else time.time()),
                "update": info.to_dict() if info else None,
            },
        )
    except OSError:
        log.warning("Update-Cache konnte nicht gespeichert werden.")


def cache_is_fresh(checked_at: int, now: float | None = None) -> bool:
    stamp = now if now is not None else time.time()
    return checked_at > 0 and 0 <= stamp - checked_at < CHECK_INTERVAL


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def write_update_helper(
    installer: Path,
    app_exe: Path,
    pid: int,
    data_root: Path,
    restart: bool = True,
) -> Path:
    """Schreibt ein kleines PowerShell-Skript, das die App beendet und updatet."""
    helper_dir = data_root / "update"
    helper_dir.mkdir(parents=True, exist_ok=True)
    helper = helper_dir / "apply_update.ps1"
    log_path = data_root / "logs" / "update.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    restart_line = (
        f"if (Test-Path -LiteralPath {_ps_quote(str(app_exe))}) {{ "
        f"Start-Process -FilePath {_ps_quote(str(app_exe))} }}"
        if restart
        else "Write-Log 'Neustart deaktiviert'"
    )
    script = f"""$ErrorActionPreference = 'Continue'
$log = {_ps_quote(str(log_path))}
function Write-Log([string]$message) {{
    try {{
        Add-Content -LiteralPath $log -Encoding UTF8 -Value (
            (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + ' ' + $message
        )
    }} catch {{ }}
}}
Write-Log 'Updater gestartet'
try {{
    Wait-Process -Id {int(pid)} -Timeout 120 -ErrorAction SilentlyContinue
}} catch {{
    Write-Log ('Warten auf Anwendung: ' + $_)
}}
Start-Sleep -Milliseconds 600
try {{
    $process = Start-Process -FilePath {_ps_quote(str(installer))} `
        -ArgumentList '/S' -Wait -PassThru
    Write-Log ('Installer beendet, ExitCode ' + $process.ExitCode)
}} catch {{
    Write-Log ('Installer-Fehler: ' + $_)
}}
Start-Sleep -Milliseconds 800
{restart_line}
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""
    with open(helper, "w", encoding="utf-8-sig", newline="\r\n") as handle:
        handle.write(script)
        handle.flush()
        os.fsync(handle.fileno())
    return helper


def launch_update_helper(
    installer: Path,
    app_exe: Path,
    pid: int,
    data_root: Path,
    restart: bool = True,
) -> None:
    """Startet den Installer nach dem Beenden dieser Anwendung, ohne Adminrechte."""
    if not installer.is_file():
        raise UpdateError("Der heruntergeladene Installer fehlt.")
    if installer.suffix.lower() != ".exe" or not installer.name.startswith(INSTALLER_PREFIX):
        raise UpdateError("Die Update-Datei ist unerwartet.")
    helper = write_update_helper(installer, app_exe, pid, data_root, restart=restart)
    system_root = Path(os.environ.get("SystemRoot", r"C:\Windows"))
    powershell = system_root / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        powershell = Path("powershell.exe")
    flags = 0
    if os.name == "nt":
        flags = 0x08000000 | 0x00000008  # CREATE_NO_WINDOW | DETACHED_PROCESS
    subprocess.Popen(
        [
            str(powershell),
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(helper),
        ],
        cwd=str(helper.parent),
        creationflags=flags,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    log.info("Update-Helfer gestartet: %s", helper)
