import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_version = load_module(
    "check_version", ROOT / "packaging" / "check_version.py"
)
publish_repo = load_module(
    "publish_repo", ROOT / "packaging" / "publish_repo.py"
)


class VersionDeclarationTests(unittest.TestCase):
    def test_release_versions_agree(self) -> None:
        versions = check_version.declared_versions()

        self.assertEqual(len(set(versions.values())), 1)


class ReleaseWorkflowTests(unittest.TestCase):
    def test_git_is_installed_before_release_checkout(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text()

        self.assertLess(
            workflow.index("- name: Install package dependencies"),
            workflow.index("- name: Check out release tag"),
        )


class PublishedRepositoryRetentionTests(unittest.TestCase):
    def test_base_and_two_newest_releases_are_retained(self) -> None:
        releases = [
            {"id": 40, "tag_name": "v0.4.0", "draft": False},
            {"id": 41, "tag_name": "v0.4.1", "draft": False},
            {"id": 42, "tag_name": "v0.4.2", "draft": False},
            {"id": 43, "tag_name": "v0.4.3", "draft": False},
            {"id": 99, "tag_name": "nightly", "draft": False},
        ]

        self.assertEqual(
            publish_repo.retained_release_ids(releases), {40, 42, 43}
        )

    def test_drafts_are_not_published(self) -> None:
        releases = [
            {"id": 44, "tag_name": "v0.4.4", "draft": True},
            {"id": 43, "tag_name": "v0.4.3", "draft": False},
        ]

        self.assertEqual(publish_repo.retained_release_ids(releases), {43})

    def test_only_arch_package_assets_are_selected(self) -> None:
        release = {
            "assets": [
                {"name": "nzb-compass-0.4.4-1-any.pkg.tar.zst"},
                {"name": "SHA256SUMS"},
                {"name": "source.tar.gz"},
            ]
        }

        self.assertEqual(
            [asset["name"] for asset in publish_repo.package_assets(release)],
            ["nzb-compass-0.4.4-1-any.pkg.tar.zst"],
        )
