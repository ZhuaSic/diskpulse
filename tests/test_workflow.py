"""Penjaga konfigurasi CI.

CI tidak bisa diuji dengan menjalankannya di lokal, jadi aturan yang dulu
membuat pipeline merah diuji di sini sebagai teks. Ini bukan tes gaya-gayaan:
ketiga kegagalan nyata di riwayat repo berasal dari hal-hal yang dicek di
bawah (runner 26.04 tanpa Python 3.9, path /tmp, dan `mkdir -p`).
"""

import re
import unittest
from pathlib import Path

WORKFLOW = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"
PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


class WorkflowTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text(encoding="utf-8")
        cls.body = "\n".join(l for l in cls.text.splitlines() if not l.strip().startswith("#"))

    def test_runner_linux_dipin_bukan_ubuntu_latest(self):
        """ubuntu-latest = Ubuntu 26.04, tanpa binary Python 3.9.

        Gagal dengan: The version '3.9' ... was not found for Ubuntu 26.04.
        """
        os_line = [l for l in self.body.splitlines() if re.search(r"^\s*os:\s*\[", l)][0]
        self.assertNotIn("ubuntu-latest", os_line, f"runner dipin salah: {os_line}")
        self.assertIn("ubuntu-24.04", os_line)

    def test_tidak_ada_path_unix_khusus(self):
        """`/tmp/...` tidak ada di Windows; pakai tempfile/pathlib."""
        untuk_dilarang = ["/tmp/", "/dev/zero", "/dev/null", "mkdir -p"]
        for pola in untuk_dilarang:
            self.assertNotIn(pola, self.body, f"CI memakai '{pola}' yang tidak portabel")

    def test_versi_python_ci_mencakup_minimum_pyproject(self):
        m = re.search(r'requires-python\s*=\s*">=\s*([0-9.]+)"', PYPROJECT.read_text(encoding="utf-8"))
        minimum = m.group(1)
        self.assertIn(f'"{minimum}"', self.body, f"CI tidak menguji Python minimum {minimum}")

    def test_semua_subcommand_di_smoke(self):
        for sub in ("scan", "health", "duplicates", "clean-plan", "watch", "diff"):
            self.assertIn(f"diskpulse {sub}", self.body, f"subcommand '{sub}' tidak diuji CI")

    def test_run_lama_dibatalkan_saat_push_baru(self):
        self.assertIn("concurrency:", self.body)
        self.assertIn("cancel-in-progress: true", self.body)


if __name__ == "__main__":
    unittest.main()
