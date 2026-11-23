"""检查资料交换格式和清单读取边界。"""
import json
from pathlib import Path
import tempfile
import unittest

from inspect_bundle import inspect_bundle


class BundleTest(unittest.TestCase):
    def test_all_declared_tables_are_readable(self):
        bundle = Path(__file__).resolve().parents[1] / "data"
        manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(manifest), {p.name for p in bundle.glob("*.csv")})
        lengths = inspect_bundle(bundle, manifest)
        self.assertTrue(all(size > 0 for size in lengths.values()))

    def test_rejects_bad_header_or_short_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for content in ("wrong,value\n1,2\n", "id,value\n1\n"):
                with self.subTest(content=content):
                    (root / "sample.csv").write_text(content, encoding="utf-8")
                    with self.assertRaises(ValueError):
                        inspect_bundle(root, {"sample.csv": ["id", "value"]})


if __name__ == "__main__":
    unittest.main()
