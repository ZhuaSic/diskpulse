import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diskpulse.cli import build_parser, main
from diskpulse.core import (DEFAULT_EXCLUDES, FileInfo, clean_plan,
                            find_duplicates, human_size, iter_files,
                            parse_size, scan)


class HumanSizeTest(unittest.TestCase):
    def test_nilai_dasar(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(1024), "1.0 KB")
        self.assertEqual(human_size(1024 ** 2), "1.0 MB")
        self.assertEqual(human_size(1536), "1.5 KB")

    def test_tidak_pernah_lebih_dari_pb(self):
        self.assertTrue(human_size(1024 ** 7).endswith("PB"))


class ParseSizeTest(unittest.TestCase):
    def test_suffix(self):
        self.assertEqual(parse_size("1K"), 1024)
        self.assertEqual(parse_size("1M"), 1024 ** 2)
        self.assertEqual(parse_size("2G"), 2 * 1024 ** 3)
        self.assertEqual(parse_size("500"), 500)

    def test_case_insensitive_dan_b_suffix(self):
        self.assertEqual(parse_size("1m"), 1024 ** 2)
        self.assertEqual(parse_size("10MB"), 10 * 1024 ** 2)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_size("")


class IterFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.py").write_text("x")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "b.py").write_text("yy")
        (self.root / ".secret").write_text("hidden")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "config").write_text("z")
        (self.root / "__pycache__").mkdir()
        (self.root / "__pycache__" / "c.pyc").write_text("w")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "lib.js").write_text("v")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, **kwargs):
        return sorted(p.name for p, _ in iter_files(self.root, **kwargs))

    def test_default_menyaring_cache_dan_tersembunyi(self):
        got = self.names()
        self.assertIn("a.py", got)
        self.assertIn("b.py", got)
        self.assertNotIn(".secret", got)
        self.assertNotIn("config", got)
        self.assertNotIn("c.pyc", got)
        self.assertNotIn("lib.js", got)

    def test_hidden_menyertakan_tersembunyi(self):
        got = self.names(hidden=True)
        self.assertIn(".secret", got)
        self.assertNotIn("c.pyc", got, "exclude tetap berlaku")

    def test_excludes_kustom_menimpa_default(self):
        got = self.names(excludes=frozenset({"a.py"}))
        self.assertNotIn("a.py", got)
        self.assertIn("lib.js", got, "node_modules tidak lagi dikecualikan")


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "big.bin").write_bytes(b"0" * 2048)
        (self.root / "small.txt").write_text("hi")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "mid.dat").write_bytes(b"1" * 1024)

    def tearDown(self):
        self.tmp.cleanup()

    def test_total_dan_jumlah(self):
        r = scan(self.root)
        self.assertEqual(r.file_count, 3)
        self.assertEqual(r.total_bytes, 2048 + 2 + 1024)

    def test_terbesar_terurut(self):
        r = scan(self.root)
        self.assertEqual(r.largest[0].path, "big.bin")
        self.assertEqual([i.size for i in r.largest],
                         sorted([i.size for i in r.largest], reverse=True))

    def test_limit(self):
        self.assertEqual(len(scan(self.root, limit=1).largest), 1)

    def test_direktori_dan_ekstensi(self):
        r = scan(self.root)
        self.assertIn("sub", r.directories)
        self.assertIn(".bin", r.extensions)

    def test_json_valid(self):
        r = scan(self.root)
        data = json.loads(__import__("diskpulse.core", fromlist=["as_json"]).as_json(r))
        self.assertEqual(data["file_count"], 3)


class DuplicatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_menemukan_isi_identik(self):
        (self.root / "a.txt").write_text("sama")
        (self.root / "b.txt").write_text("sama")
        (self.root / "c.txt").write_text("beda")
        groups = find_duplicates(self.root, min_size=1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_min_size_menyaring(self):
        (self.root / "a.txt").write_text("x")
        (self.root / "b.txt").write_text("x")
        self.assertEqual(find_duplicates(self.root, min_size=100), [])

    def test_tiga_salinan(self):
        for n in "abc":
            (self.root / f"{n}.txt").write_text("identik")
        groups = find_duplicates(self.root, min_size=1)
        self.assertEqual(len(groups[0]), 3)

    def test_urut_berdasarkan_potensi_hemat(self):
        for n in "ab":
            (self.root / f"kecil{n}.txt").write_text("k")
        for n in "abc":
            (self.root / f"besar{n}.bin").write_bytes(b"X" * 5000)
        groups = find_duplicates(self.root, min_size=1)
        self.assertEqual(groups[0][0].size, 5000)


class CleanPlanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old = self.root / "old.txt"
        self.old.write_text("lama")
        past = time.time() - 400 * 86400
        os.utime(self.old, (past, past))
        self.new = self.root / "new.txt"
        self.new.write_text("baru")

    def tearDown(self):
        self.tmp.cleanup()

    def test_hanya_file_lama(self):
        files = clean_plan(self.root, days=180)
        self.assertEqual([f.path for f in files], ["old.txt"])

    def test_days_nol_menyertakan_semua(self):
        self.assertEqual(len(clean_plan(self.root, days=0)), 2)

    def test_tidak_menghapus_apa_pun(self):
        clean_plan(self.root, days=0)
        self.assertTrue(self.old.exists())
        self.assertTrue(self.new.exists())

    def test_age_days(self):
        files = clean_plan(self.root, days=180)
        self.assertGreater(files[0].age_days, 300)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "x.txt").write_text("abc")

    def tearDown(self):
        self.tmp.cleanup()

    def test_parser_semua_subcommand(self):
        p = build_parser()
        for cmd in ("scan", "duplicates", "clean-plan"):
            self.assertEqual(p.parse_args([cmd]).command, cmd)

    def test_main_scan_json(self):
        self.assertEqual(main(["scan", str(self.root), "--json"]), 0)

    def test_main_direktori_tidak_ada(self):
        self.assertEqual(main(["scan", str(self.root / "tidak-ada")]), 2)

    def test_main_min_size_invalid(self):
        self.assertEqual(main(["duplicates", str(self.root), "--min-size", ""]), 2)

    def test_version(self):
        r = subprocess.run([sys.executable, "-m", "diskpulse", "--version"],
                           capture_output=True, text=True,
                           cwd=str(Path(__file__).resolve().parent.parent))
        self.assertEqual(r.returncode, 0)
        self.assertIn("0.1.0", r.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
