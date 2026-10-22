import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from gaubenmaster.updater import (  # noqa: E402
    API_URL,
    CHECKSUMS_NAME,
    CHECK_INTERVAL,
    MIN_INSTALLER_SIZE,
    UpdateError,
    UpdateInfo,
    cache_is_fresh,
    download_and_verify,
    fetch_latest_release,
    installer_filename,
    parse_checksums,
    read_cache,
    save_cache,
    write_update_helper,
)


class FakeResponse:
    def __init__(self, body=b"", status=200, headers=None, chunk=None):
        self._body = body
        self._pos = 0
        self._chunk = chunk
        self.status = status
        self.headers = headers or {}

    def read(self, size=-1):
        if size is None or size < 0:
            data = self._body[self._pos :]
            self._pos = len(self._body)
            return data
        limit = size if self._chunk is None else min(size, self._chunk)
        data = self._body[self._pos : self._pos + limit]
        self._pos += len(data)
        return data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeOpener:
    def __init__(self, routes):
        self.routes = routes
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append(request.full_url)
        result = self.routes.get(request.full_url)
        if result is None:
            raise URLError("not found")
        if isinstance(result, BaseException):
            raise result
        if callable(result):
            return result(request)
        return result


def release_payload(version="1.1.0", size=MIN_INSTALLER_SIZE + 100, **overrides):
    tag = f"v{version}"
    name = installer_filename(version)
    base = f"https://github.com/soendi/GaubenMaster2/releases/download/{tag}"
    payload = {
        "tag_name": tag,
        "draft": False,
        "prerelease": False,
        "body": "Aenderungen",
        "assets": [
            {
                "name": name,
                "size": size,
                "browser_download_url": f"{base}/{name}",
            },
            {
                "name": CHECKSUMS_NAME,
                "size": 100,
                "browser_download_url": f"{base}/{CHECKSUMS_NAME}",
            },
        ],
    }
    payload.update(overrides)
    return payload


def api_response(payload):
    return FakeResponse(json.dumps(payload).encode("utf-8"))


def checksum_text(name, digest):
    return f"{digest}  {name}\n"


def build_info(version="1.1.0", size=MIN_INSTALLER_SIZE + 100):
    payload = release_payload(version, size)
    installer, checksums = payload["assets"]
    return UpdateInfo(
        version=version,
        tag=f"v{version}",
        notes="Aenderungen",
        installer_url=installer["browser_download_url"],
        installer_name=installer["name"],
        installer_size=size,
        checksums_url=checksums["browser_download_url"],
    )


class ReleaseTests(unittest.TestCase):
    def test_newer_release_is_detected(self):
        opener = FakeOpener({API_URL: api_response(release_payload("1.1.0"))})
        info = fetch_latest_release("1.0.0", opener=opener)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.version, "1.1.0")
        self.assertEqual(info.tag, "v1.1.0")
        self.assertEqual(info.installer_name, "GaubenMaster2-Setup-1.1.0.exe")
        self.assertGreaterEqual(info.installer_size, MIN_INSTALLER_SIZE)
        self.assertTrue(info.installer_url.startswith("https://github.com/"))
        self.assertEqual(len(opener.requests), 1)

    def test_same_or_older_release_is_no_update(self):
        for version in ("1.0.0", "0.9.9"):
            with self.subTest(version=version):
                opener = FakeOpener({API_URL: api_response(release_payload(version))})
                self.assertIsNone(fetch_latest_release("1.0.0", opener=opener))

    def test_draft_and_prerelease_are_ignored(self):
        for flag in ("draft", "prerelease"):
            with self.subTest(flag=flag):
                opener = FakeOpener(
                    {API_URL: api_response(release_payload("1.1.0", **{flag: True}))}
                )
                self.assertIsNone(fetch_latest_release("1.0.0", opener=opener))

    def test_invalid_tag_is_rejected(self):
        for tag in ("1.1.0", "v1.1.0-beta", "v2", "v01.1.0"):
            with self.subTest(tag=tag):
                opener = FakeOpener({API_URL: api_response(release_payload("1.1.0", tag_name=tag))})
                with self.assertRaises(UpdateError):
                    fetch_latest_release("1.0.0", opener=opener)

    def test_missing_assets_are_rejected(self):
        payload = release_payload("1.1.0")
        payload["assets"] = payload["assets"][:1]
        opener = FakeOpener({API_URL: api_response(payload)})
        with self.assertRaises(UpdateError):
            fetch_latest_release("1.0.0", opener=opener)

    def test_wrong_host_is_rejected(self):
        payload = release_payload("1.1.0")
        payload["assets"][0]["browser_download_url"] = (
            "https://evil.example/GaubenMaster2-Setup-1.1.0.exe"
        )
        opener = FakeOpener({API_URL: api_response(payload)})
        with self.assertRaises(UpdateError):
            fetch_latest_release("1.0.0", opener=opener)

    def test_wrong_repository_path_is_rejected(self):
        payload = release_payload("1.1.0")
        payload["assets"][0]["browser_download_url"] = (
            "https://github.com/evil/repo/releases/download/v1.1.0/"
            "GaubenMaster2-Setup-1.1.0.exe"
        )
        opener = FakeOpener({API_URL: api_response(payload)})
        with self.assertRaises(UpdateError):
            fetch_latest_release("1.0.0", opener=opener)

    def test_implausible_size_is_rejected(self):
        opener = FakeOpener(
            {API_URL: api_response(release_payload("1.1.0", size=12))}
        )
        with self.assertRaises(UpdateError):
            fetch_latest_release("1.0.0", opener=opener)

    def test_http_and_network_errors(self):
        for error in (HTTPError(API_URL, 500, "fail", {}, None), URLError("offline")):
            with self.subTest(error=type(error).__name__):
                opener = FakeOpener({API_URL: error})
                with self.assertRaises(UpdateError):
                    fetch_latest_release("1.0.0", opener=opener)

    def test_unreadable_json_is_rejected(self):
        opener = FakeOpener({API_URL: FakeResponse(b"<html>")})
        with self.assertRaises(UpdateError):
            fetch_latest_release("1.0.0", opener=opener)

    def test_oversized_api_response_is_rejected(self):
        opener = FakeOpener({API_URL: FakeResponse(b"x" * (1024 * 1024 + 1))})
        with self.assertRaises(UpdateError):
            fetch_latest_release("1.0.0", opener=opener)


class ChecksumTests(unittest.TestCase):
    def test_parse(self):
        digest = "a" * 64
        text = (
            f"# comment\n{digest}  file.exe\n{'b' * 64} *other.exe\ninvalid line\n"
        )
        result = parse_checksums(text)
        self.assertEqual(result["file.exe"], digest)
        self.assertEqual(result["other.exe"], "b" * 64)
        self.assertEqual(len(result), 2)


class DownloadTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.dir = Path(self.temp.name)
        self.info = build_info()
        self.payload = b"x" * self.info.installer_size
        self.digest = hashlib.sha256(self.payload).hexdigest()

    def tearDown(self):
        self.temp.cleanup()

    def _routes(self, payload=None, digest=None, checksums_status=200):
        payload = self.payload if payload is None else payload
        digest = self.digest if digest is None else digest
        return {
            self.info.installer_url: FakeResponse(
                payload,
                headers={"Content-Length": str(len(payload))},
                chunk=8192,
            ),
            self.info.checksums_url: FakeResponse(
                checksum_text(self.info.installer_name, digest).encode(),
                status=checksums_status,
            ),
        }

    def test_download_verifies_and_replaces_atomically(self):
        progress = []
        path = download_and_verify(
            self.info,
            self.dir,
            opener=FakeOpener(self._routes()),
            progress=lambda done, total: progress.append(done),
        )
        self.assertTrue(path.is_file())
        self.assertEqual(path.read_bytes(), self.payload)
        self.assertFalse(path.with_name(path.name + ".part").exists())
        self.assertEqual(progress[0], 0)
        self.assertEqual(progress[-1], self.info.installer_size)

    def test_checksum_mismatch_is_rejected_and_part_removed(self):
        with self.assertRaises(UpdateError):
            download_and_verify(
                self.info,
                self.dir,
                opener=FakeOpener(self._routes(digest="0" * 64)),
            )
        self.assertFalse(
            (self.dir / (self.info.installer_name + ".part")).exists()
        )
        self.assertFalse((self.dir / self.info.installer_name).exists())

    def test_missing_checksum_entry_is_rejected(self):
        routes = self._routes()
        routes[self.info.checksums_url] = FakeResponse(
            f"{self.digest}  other.exe\n".encode()
        )
        with self.assertRaises(UpdateError):
            download_and_verify(self.info, self.dir, opener=FakeOpener(routes))

    def test_truncated_download_is_rejected(self):
        payload = self.payload[:-100]
        with self.assertRaises(UpdateError):
            download_and_verify(
                self.info, self.dir, opener=FakeOpener(self._routes(payload=payload))
            )

    def test_http_error_is_rejected(self):
        routes = self._routes()
        routes[self.info.installer_url] = FakeResponse(status=404)
        with self.assertRaises(UpdateError):
            download_and_verify(self.info, self.dir, opener=FakeOpener(routes))

    def test_network_abort_is_rejected(self):
        routes = self._routes()
        routes[self.info.installer_url] = URLError("connection reset")
        with self.assertRaises(UpdateError):
            download_and_verify(self.info, self.dir, opener=FakeOpener(routes))

    def test_checksums_http_error_is_rejected(self):
        routes = self._routes(checksums_status=500)
        with self.assertRaises(UpdateError):
            download_and_verify(self.info, self.dir, opener=FakeOpener(routes))

    def test_checksums_oversized_is_rejected(self):
        routes = self._routes()
        routes[self.info.checksums_url] = FakeResponse(b"x" * (256 * 1024 + 1))
        with self.assertRaises(UpdateError):
            download_and_verify(self.info, self.dir, opener=FakeOpener(routes))


class CacheTests(unittest.TestCase):
    def test_fresh_and_stale(self):
        self.assertTrue(cache_is_fresh(1000, now=1000 + CHECK_INTERVAL - 1))
        self.assertFalse(cache_is_fresh(1000, now=1000 + CHECK_INTERVAL))
        self.assertFalse(cache_is_fresh(0, now=1000))
        self.assertFalse(cache_is_fresh(2000, now=1000))

    def test_roundtrip_and_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            info = build_info()
            save_cache(path, info, now=1234)
            checked, cached = read_cache(path)
            self.assertEqual(checked, 1234)
            self.assertEqual(cached, info)
            path.write_text("{broken", encoding="utf-8")
            self.assertEqual(read_cache(path), (0, None))
            save_cache(path, None, now=99)
            self.assertEqual(read_cache(path), (99, None))


class HelperTests(unittest.TestCase):
    def test_helper_contains_quoted_paths_and_wait(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            installer = base / "Ordner mit 'Quote'" / "GaubenMaster2-Setup-1.1.0.exe"
            installer.parent.mkdir()
            installer.write_bytes(b"x")
            app = base / "Program Files" / "GaubenMaster2.exe"
            helper = write_update_helper(
                installer, app, 4321, base / "data", restart=True
            )
            text = helper.read_text(encoding="utf-8-sig")
            self.assertIn("Wait-Process -Id 4321", text)
            self.assertIn("ArgumentList '/S'", text)
            self.assertIn("Ordner mit ''Quote''", text)
            self.assertIn("Start-Process -FilePath", text)

    def test_helper_without_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            helper = write_update_helper(
                base / "setup.exe", base / "app.exe", 1, base, restart=False
            )
            text = helper.read_text(encoding="utf-8-sig")
            self.assertIn("Neustart deaktiviert", text)
            self.assertNotIn("Start-Process -FilePath 'app", text)


class CacheValidationTests(unittest.TestCase):
    def test_invalid_cached_assets_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text(
                json.dumps(
                    {
                        "checked_at": 100,
                        "update": {
                            "version": "2.0.0",
                            "tag": "v2.0.0",
                            "notes": "",
                            "installer_url": "https://evil.example/x.exe",
                            "installer_name": "GaubenMaster2-Setup-2.0.0.exe",
                            "installer_size": MIN_INSTALLER_SIZE,
                            "checksums_url": "https://evil.example/SHA256SUMS.txt",
                        },
                    }
                ),
                encoding="utf-8",
            )
            self.assertEqual(read_cache(path), (0, None))


if __name__ == "__main__":
    unittest.main()
