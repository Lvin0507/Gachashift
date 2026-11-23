"""The one-click update: what it downloads, what it refuses, and what the updater does."""

import hashlib
import io
import pathlib
import tempfile
import unittest
import zipfile
from unittest import mock

from gachashift import selfupdate, updates
from gachashift.updates import Release

ZIP_URL = "https://github.com/Lvin0507/Gachashift/releases/download/v1.2.0/Gachashift-1.2.0.zip"


def release_zip(extra=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Gachashift/Gachashift.exe", b"new exe")
        z.writestr("Gachashift/_internal/lib.dll", b"lib")
        z.writestr("Gachashift/LICENSE", b"MIT")
        for name, data in (extra or {}).items():
            z.writestr(name, data)
    return buf.getvalue()


class FakeResponse:
    def __init__(self, data):
        self.data = data
        self.ok = True
        self.text = data.decode(errors="ignore")

    def raise_for_status(self):
        pass

    def iter_content(self, size):
        for i in range(0, len(self.data), size):
            yield self.data[i:i + size]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class ReleaseTest(unittest.TestCase):
    def test_github_digest(self):
        rel = updates.release_from({"tag_name": "v1.2.0", "html_url": "page", "assets": [
            {"name": "Gachashift-1.2.0.zip", "browser_download_url": ZIP_URL, "size": 10,
             "digest": "sha256:ABC123"}]})
        self.assertEqual((rel.version, rel.zip_url, rel.zip_size, rel.sha256), ("1.2.0", ZIP_URL, 10, "abc123"))

    def test_checksum_file(self):
        rel = updates.release_from({"tag_name": "v1.2.0", "assets": [
            {"name": "Gachashift-1.2.0.zip", "browser_download_url": ZIP_URL},
            {"name": "Gachashift-1.2.0.zip.sha256", "browser_download_url": ZIP_URL + ".sha256"}]})
        self.assertEqual((rel.sha256, rel.sha256_url), ("", ZIP_URL + ".sha256"))

    def test_no_zip(self):
        self.assertEqual(updates.release_from({"tag_name": "v1.2.0", "assets": []}).zip_url, "")


class DownloadTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dest = pathlib.Path(self.tmp.name) / "update.zip"
        self.data = release_zip()

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, url, **kwargs):
        if url.endswith(".sha256"):
            return FakeResponse(f"{hashlib.sha256(self.data).hexdigest()}  Gachashift-1.2.0.zip\n".encode())
        return FakeResponse(self.data)

    def test_good_download(self):
        rel = Release("1.2.0", "page", ZIP_URL, len(self.data), sha256=hashlib.sha256(self.data).hexdigest())
        seen = []
        with mock.patch.object(selfupdate.requests, "get", self.get):
            selfupdate.download(rel, self.dest, seen.append)
        self.assertEqual(self.dest.read_bytes(), self.data)
        self.assertEqual(seen[-1], 100)

    def test_checksum_from_file(self):
        rel = Release("1.2.0", "page", ZIP_URL, sha256_url=ZIP_URL + ".sha256")
        with mock.patch.object(selfupdate.requests, "get", self.get):
            selfupdate.download(rel, self.dest)
        self.assertTrue(self.dest.exists())

    def test_tampered_download_is_thrown_away(self):
        rel = Release("1.2.0", "page", ZIP_URL, sha256="0" * 64)
        with mock.patch.object(selfupdate.requests, "get", self.get):
            with self.assertRaises(selfupdate.UpdateError):
                selfupdate.download(rel, self.dest)
        self.assertFalse(self.dest.exists())

    def test_no_checksum_no_update(self):
        with self.assertRaises(selfupdate.UpdateError):
            selfupdate.download(Release("1.2.0", "page", ZIP_URL), self.dest)

    def test_only_from_github(self):
        rel = Release("1.2.0", "page", "https://example.com/Gachashift-1.2.0.zip", sha256="0" * 64)
        with self.assertRaises(selfupdate.UpdateError):
            selfupdate.download(rel, self.dest)


class UnpackTest(unittest.TestCase):
    def unpack(self, data):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        zip_path = pathlib.Path(tmp.name) / "u.zip"
        zip_path.write_bytes(data)
        return selfupdate.unpack(zip_path, pathlib.Path(tmp.name) / "files"), pathlib.Path(tmp.name)

    def test_finds_the_program(self):
        folder, _ = self.unpack(release_zip())
        self.assertTrue((folder / "Gachashift.exe").exists())
        self.assertEqual(folder.name, "Gachashift")

    def test_refuses_paths_outside(self):
        with self.assertRaises(selfupdate.UpdateError):
            self.unpack(release_zip({"../../evil.exe": b"x"}))

    def test_refuses_a_zip_without_the_program(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("readme.txt", b"hi")
        with self.assertRaises(selfupdate.UpdateError):
            self.unpack(buf.getvalue())


class ScriptTest(unittest.TestCase):
    def test_script(self):
        text = selfupdate.updater_script(r"C:\Temp\u\files\Gachashift", r"D:\游戏\Gachashift", 4242,
                                         r"D:\游戏\Gachashift\logs\update.log", r"C:\Temp\u")
        lines = text.split("\r\n")
        self.assertIn('tasklist /FI "PID eq 4242"', text)                     # waits for the app
        self.assertIn(r'"D:\游戏\Gachashift\_internal" /MIR', text)           # libraries mirrored
        mirror = [l for l in lines if "/MIR" in l]
        self.assertEqual(len(mirror), 1)
        self.assertNotIn('"D:\\游戏\\Gachashift" /MIR', text)                 # never mirror the whole folder
        self.assertIn("/XF config.json", text)
        self.assertIn(r'start "" "D:\游戏\Gachashift\Gachashift.exe"', text)  # opens the new version
        self.assertTrue(lines[-2].endswith(r'rmdir /s /q "C:\Temp\u"'))       # cleans up last

    def test_prepare(self):
        data = release_zip()
        rel = Release("1.2.0", "page", ZIP_URL, len(data), sha256=hashlib.sha256(data).hexdigest())
        with tempfile.TemporaryDirectory() as install:
            with mock.patch.object(selfupdate, "app_dir", lambda: pathlib.Path(install)), \
                    mock.patch.object(selfupdate.requests, "get", lambda url, **k: FakeResponse(data)):
                script = selfupdate.prepare(rel)
            self.assertTrue(script.exists())
            self.assertTrue((script.parent / "files" / "Gachashift" / "Gachashift.exe").exists())
            self.assertFalse((script.parent / "update.zip").exists())
            self.assertTrue((pathlib.Path(install) / "logs").is_dir())
            text = script.read_text(encoding="utf-8")
            self.assertIn(str(script.parent), text)
        import shutil
        shutil.rmtree(script.parent, ignore_errors=True)


class FromSourceTest(unittest.TestCase):
    def test_source_checkout_cannot_replace_itself(self):
        self.assertFalse(selfupdate.can_self_update())


if __name__ == "__main__":
    unittest.main()
