import unittest
from datetime import timezone

from nzb_compass.models import Indexer, Release


class ReleaseTests(unittest.TestCase):
    def test_release_parses_prowlarr_payload(self) -> None:
        release = Release.from_prowlarr(
            {
                "title": "Example.Release.1080p-GROUP",
                "guid": "abc-123",
                "downloadUrl": "http://localhost:9696/api/v1/indexer/1/download?link=x",
                "indexer": "ExampleNZB",
                "indexerId": 1,
                "size": 1_610_612_736,
                "publishDate": "2026-08-10T12:30:00Z",
                "categories": [{"id": 2040, "name": "Movies/HD"}],
                "protocol": "usenet",
                "grabs": 17,
            }
        )

        self.assertEqual(release.title, "Example.Release.1080p-GROUP")
        self.assertEqual(release.categories, ["Movies/HD"])
        self.assertIsNotNone(release.publish_date)
        self.assertEqual(release.publish_date.tzinfo, timezone.utc)
        self.assertEqual(release.size_label, "1.5 GB")
        self.assertEqual(release.protocol, "usenet")

    def test_release_handles_sparse_payload(self) -> None:
        release = Release.from_prowlarr({})

        self.assertEqual(release.title, "Untitled release")
        self.assertEqual(release.size_label, "0 B")
        self.assertEqual(release.age_label, "Unknown age")

    def test_indexer_parses_search_state(self) -> None:
        indexer = Indexer.from_prowlarr(
            {
                "id": 7,
                "name": "ExampleNZB",
                "protocol": "usenet",
                "enable": True,
                "supportsSearch": True,
                "privacy": "private",
                "priority": 10,
            }
        )

        self.assertEqual(indexer.id, 7)
        self.assertEqual(indexer.name, "ExampleNZB")
        self.assertTrue(indexer.enabled_in_prowlarr)
        self.assertTrue(indexer.supports_search)
        self.assertEqual(indexer.protocol, "usenet")

    def test_game_categories_are_grouped_together(self) -> None:
        console = Release.from_prowlarr(
            {"categories": [{"id": 1010, "name": "Console/NDS"}]}
        )
        pc_game = Release.from_prowlarr(
            {"categories": [{"id": 4050, "name": "PC/Games"}]}
        )
        software = Release.from_prowlarr(
            {"categories": [{"id": 4010, "name": "PC/0day"}]}
        )

        self.assertEqual(console.content_type, "Games")
        self.assertEqual(pc_game.content_type, "Games")
        self.assertEqual(software.content_type, "Software")

    def test_media_categories_are_classified(self) -> None:
        movie = Release.from_prowlarr(
            {"categories": [{"id": 2040, "name": "Movies/HD"}]}
        )
        television = Release.from_prowlarr(
            {"categories": [{"id": 5040, "name": "TV/HD"}]}
        )

        self.assertEqual(movie.content_type, "Movies")
        self.assertEqual(television.content_type, "TV")
