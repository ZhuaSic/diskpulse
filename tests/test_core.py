import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diskpulse.classify import (BUILD, CACHE, DEPS, LOG, REGENERABLE, UNIQUE,
                                VCS, classify, sort_kinds)
from diskpulse.cli import build_parser, main
from diskpulse.core import (clean_plan, diff_scans, find_duplicates, health,
                            human_size, iter_files, parse_size, scan, snapshot)


class HumanSizeTest(unittest.TestCase):
    def test_nilai_dasar(self):
        self.assertEqual(human_size(0), "0 B")
        self.assertEqual(human_size(512), "512 B")
        self.assertEqual(human_size(1024), "1.0 KB")
        self.assertEqual(human_size(1536), "1.5 KB")
        self.assertEqual(human_size(1024 ** 2), "1.0 MB")

    def test_naik_satuan_sampai_pb_dan_lebih(self):
        self.assertTrue(human_size(1024 ** 5).endswith("PB"), human_size(1024 ** 5))
        self.assertTrue(human_size(1024 ** 6).endswith("EB"), human_size(1024 ** 6))
        self.assertEqual(human_size(1024 ** 7).split()[1], "ZB")
        self.assertEqual(human_size(1024 ** 8).split()[1], "YB")


class ParseSizeTest(unittest.TestCase):
    def test_suffix(self):
        for text, want in [("1K", 1024), ("1M", 1024 ** 2), ("2G", 2 * 1024 ** 3),
                           ("500", 500), ("1m", 1024 ** 2), ("10MB", 10 * 1024 ** 2)]:
            self.assertEqual(parse_size(text), want, text)

    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_size("")


class ClassifyTest(unittest.TestCase):
    """Inti pembeda: bedakan sampah yang bisa dibuat ulang vs data unik."""

    def test_node_modules_adalah_dependensi(self):
        self.assertEqual(classify(Path("app/node_modules/react/index.js"))[0], DEPS)

    def test_git_bukan_cache(self):
        self.assertEqual(classify(Path("repo/.git/objects/ab/cdef"))[0], VCS)

    def test_git_tidak_pernah_regenerable(self):
        self.assertNotIn(VCS, REGENERABLE)

    def test_pyc_adalah_cache(self):
        self.assertEqual(classify(Path("a/b.pyc"))[0], CACHE)

    def test_target_rust_adalah_build(self):
        self.assertEqual(classify(Path("proj/target/debug/app"))[0], BUILD)

    def test_dist_dan_out_adalah_build(self):
        for path in ("app/dist/bundle.js", "app/out/main.js",
                     "proj/storybook-static/index.html", "p/_site/index.html"):
            self.assertEqual(classify(Path(path))[0], BUILD, path)

    def test_venv_adalah_dependensi(self):
        self.assertEqual(classify(Path("proj/.venv/lib/python3/x.py"))[0], DEPS)

    def test_data_biasa_adalah_unik(self):
        self.assertEqual(classify(Path("docs/laporan.pdf"))[0], UNIQUE)

    def test_direktori_terdalam_menang(self):
        # .git di dalam node_modules harus tetap metadata VCS
        self.assertEqual(classify(Path("x/node_modules/y/.git/config"))[0], VCS)

    def test_saran_regenerasi_spesifik(self):
        self.assertIn("npm install", classify(Path("a/node_modules/b"))[1])
        self.assertIn("cargo", classify(Path("a/target/b"))[1])

    def test_log_dikenali(self):
        self.assertEqual(classify(Path("app/error.log"))[0], LOG)

    def test_sort_kinds_yang_bisa_dibebaskan_dulu(self):
        rows = sort_kinds({UNIQUE: 999, BUILD: 1, DEPS: 5})
        self.assertEqual([k for k, _ in rows][0], DEPS)
        self.assertEqual([k for k, _ in rows][-1], UNIQUE)


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
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "lib.js").write_text("v")

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, **kwargs):
        return sorted(p.name for p, _ in iter_files(self.root, **kwargs))

    def test_default_menghitung_semua_termasuk_tersembunyi(self):
        """Total harus jujur: .git dan node_modules ikut dihitung."""
        got = self.names()
        self.assertIn("a.py", got)
        self.assertIn("b.py", got)
        self.assertIn(".secret", got)
        self.assertIn("config", got)
        self.assertIn("lib.js", got)

    def test_skip_hidden(self):
        got = self.names(skip_hidden=True)
        self.assertNotIn(".secret", got)
        self.assertNotIn("config", got)
        self.assertIn("lib.js", got)

    def test_excludes_kustom(self):
        got = self.names(excludes=frozenset({"node_modules"}))
        self.assertNotIn("lib.js", got)
        self.assertIn("a.py", got)


class ScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "big.bin").write_bytes(b"0" * 2048)
        (self.root / "small.txt").write_text("hi")
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "x.js").write_bytes(b"1" * 4096)

    def tearDown(self):
        self.tmp.cleanup()

    def test_total_jujur_termasuk_node_modules(self):
        r = scan(self.root)
        self.assertEqual(r.file_count, 3)
        self.assertEqual(r.total_bytes, 2048 + 2 + 4096)

    def test_kinds_terisi(self):
        r = scan(self.root)
        self.assertEqual(r.kinds[DEPS], 4096)

    def test_reclaimable_hanya_kategori_regenerable(self):
        r = scan(self.root)
        self.assertEqual(r.reclaimable_bytes, 4096)

    def test_elapsed_dan_speed_terisi(self):
        r = scan(self.root)
        self.assertGreater(r.elapsed, 0)
        self.assertGreater(r.speed, 0)

    def test_json_valid(self):
        from diskpulse.core import as_json
        data = json.loads(as_json(scan(self.root)))
        self.assertEqual(data["file_count"], 3)
        self.assertIn("kinds", data)


class HealthTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_disk_bersih_skor_tinggi(self):
        (self.root / "doc.pdf").write_bytes(b"x" * 100)
        report = health(scan(self.root))
        self.assertGreaterEqual(report["score"], 90)
        self.assertEqual(report["grade"], "A")

    def test_cache_besar_menurunkan_skor(self):
        (self.root / "doc.pdf").write_bytes(b"x" * 100)
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "a.js").write_bytes(b"y" * 100000)
        report = health(scan(self.root))
        self.assertLess(report["score"], 100)
        kinds = [a["kind"] for a in report["actions"]]
        self.assertIn(DEPS, kinds)

    def test_saran_punya_angka(self):
        (self.root / "node_modules").mkdir()
        (self.root / "node_modules" / "a.js").write_bytes(b"y" * 5000)
        (self.root / "f.txt").write_text("z")
        report = health(scan(self.root))
        for action in report["actions"]:
            self.assertIn("human", action)
            self.assertIn("suggestion", action)
            self.assertGreater(action["bytes"], 0)

    def test_skor_tidak_pernah_negatif(self):
        (self.root / "node_modules").mkdir()
        (self.root / "logs").mkdir()
        (self.root / "node_modules" / "a.js").write_bytes(b"y" * 100000)
        (self.root / "logs" / "a.log").write_bytes(b"y" * 100000)
        (self.root / "t.txt").write_text("z")
        self.assertGreaterEqual(health(scan(self.root))["score"], 0)


class DuplicatesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_isi_identik(self):
        (self.root / "a.txt").write_text("sama")
        (self.root / "b.txt").write_text("sama")
        (self.root / "c.txt").write_text("beda")
        groups = find_duplicates(self.root, min_size=1)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(groups[0]), 2)

    def test_file_besar_lewat_partial_hash(self):
        blob = b"Z" * 300000
        (self.root / "a.bin").write_bytes(blob)
        (self.root / "b.bin").write_bytes(blob)
        groups = find_duplicates(self.root, min_size=1, fast=True)
        self.assertEqual(len(groups), 1)

    def test_file_besar_beda_tengah_tidak_duplikat(self):
        (self.root / "a.bin").write_bytes(b"A" * 150000 + b"X" + b"A" * 150000)
        (self.root / "b.bin").write_bytes(b"A" * 150000 + b"Y" + b"A" * 150000)
        self.assertEqual(find_duplicates(self.root, min_size=1, fast=True), [])

    def test_min_size(self):
        (self.root / "a.txt").write_text("x")
        (self.root / "b.txt").write_text("x")
        self.assertEqual(find_duplicates(self.root, min_size=100), [])

    def test_urut_potensi_hemat(self):
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
        self.assertEqual([f.path for f in clean_plan(self.root, days=180)], ["old.txt"])

    def test_tidak_menghapus(self):
        clean_plan(self.root, days=0)
        self.assertTrue(self.old.exists())
        self.assertTrue(self.new.exists())

    def test_age_days(self):
        self.assertGreater(clean_plan(self.root, days=180)[0].age_days, 300)


class DiffTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.txt").write_bytes(b"x" * 100)

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_lalu_diff_mendeteksi_pertumbuhan(self):
        old = snapshot(scan(self.root))
        (self.root / "b.txt").write_bytes(b"y" * 400)
        changes = diff_scans(old, scan(self.root))
        self.assertEqual(changes["delta_bytes"], 400)
        self.assertEqual(changes["current_files"], 2)

    def test_diff_tanpa_perubahan_nol(self):
        old = snapshot(scan(self.root))
        self.assertEqual(diff_scans(old, scan(self.root))["delta_bytes"], 0)


class CliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "x.txt").write_text("abc")

    def tearDown(self):
        self.tmp.cleanup()

    def test_semua_subcommand_terdaftar(self):
        p = build_parser()
        for cmd in ("scan", "health", "duplicates", "clean-plan", "watch", "diff"):
            self.assertEqual(p.parse_args([cmd]).command, cmd)

    def test_scan_json(self):
        self.assertEqual(main(["scan", str(self.root), "--json"]), 0)

    def test_health_json(self):
        self.assertEqual(main(["health", str(self.root), "--json"]), 0)

    def test_direktori_tidak_ada(self):
        self.assertEqual(main(["scan", str(self.root / "nope")]), 2)

    def test_min_size_invalid(self):
        self.assertEqual(main(["duplicates", str(self.root), "--min-size", ""]), 2)

    def test_diff_compare_tanpa_snapshot(self):
        self.assertEqual(main(["diff", str(self.root), "--compare"]), 2)

    def test_diff_save_lalu_compare(self):
        self.assertEqual(main(["diff", str(self.root)]), 0)
        self.assertEqual(main(["diff", str(self.root), "--compare"]), 0)

    def test_watch_cycles(self):
        self.assertEqual(main(["watch", str(self.root), "--interval", "0.01",
                               "--cycles", "1", "--json"]), 0)

    def test_version(self):
        from diskpulse import __version__
        r = subprocess.run([sys.executable, "-m", "diskpulse", "--version"],
                           capture_output=True, text=True,
                           cwd=str(Path(__file__).resolve().parent.parent))
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.strip(), __version__)


if __name__ == "__main__":
    unittest.main(verbosity=2)
