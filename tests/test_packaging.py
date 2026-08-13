import importlib.util
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "packaging" / "prune_output.py"
SPEC = importlib.util.spec_from_file_location("prune_output", MODULE_PATH)
assert SPEC and SPEC.loader
prune_output = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(prune_output)


class OutputRetentionTests(unittest.TestCase):
    def test_original_and_two_newest_versions_are_retained(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            names = [
                "nzb-compass-0.4.0-1-any.pkg.tar.zst",
                "nzb-compass-0.4.1-1-any.pkg.tar.zst",
                "nzb-compass-0.4.2-1-any.pkg.tar.zst",
                "nzb-compass-0.4.3-1-any.pkg.tar.zst",
                "notes.txt",
            ]
            for name in names:
                (output / name).touch()

            obsolete = {path.name for path in prune_output.obsolete_artifacts(output)}

            self.assertEqual(
                obsolete, {"nzb-compass-0.4.1-1-any.pkg.tar.zst"}
            )

    def test_all_artifacts_for_an_old_version_are_pruned_together(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            names = [
                "nzb-compass-0.4.1-1-any.pkg.tar.zst",
                "nzb-compass-0.4.1-debug.pkg.tar.zst",
                "nzb-compass-0.4.2-1-any.pkg.tar.zst",
                "nzb-compass-0.4.3-1-any.pkg.tar.zst",
                "nzb-compass-0.4.4-1-any.pkg.tar.zst",
            ]
            for name in names:
                (output / name).touch()

            removed = {
                path.name for path in prune_output.prune_output(output)
            }

            self.assertEqual(
                removed,
                {
                    "nzb-compass-0.4.1-1-any.pkg.tar.zst",
                    "nzb-compass-0.4.1-debug.pkg.tar.zst",
                    "nzb-compass-0.4.2-1-any.pkg.tar.zst",
                },
            )
            self.assertTrue((output / "nzb-compass-0.4.3-1-any.pkg.tar.zst").exists())
            self.assertTrue((output / "nzb-compass-0.4.4-1-any.pkg.tar.zst").exists())
