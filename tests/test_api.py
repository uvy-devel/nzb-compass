import unittest
from unittest.mock import patch

from nzb_compass.api import (
    ProwlarrClient,
    SabnzbdClient,
    _api_url,
    _multipart,
    _prowlarr_download_target,
)
from nzb_compass.config import Settings
from nzb_compass.models import Release


class _JsonResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


class ApiHelpersTests(unittest.TestCase):
    def test_api_url_preserves_reverse_proxy_path(self) -> None:
        self.assertEqual(
            _api_url("https://example.test/prowlarr", "/api/v1/search"),
            "https://example.test/prowlarr/api/v1/search",
        )

    def test_multipart_contains_fields_and_file(self) -> None:
        body, content_type = _multipart(
            {"mode": "addfile", "apikey": "secret"},
            "nzbfile",
            "example.nzb",
            b"<nzb />",
        )

        self.assertTrue(content_type.startswith("multipart/form-data; boundary="))
        self.assertIn(b'name="mode"', body)
        self.assertIn(b'name="nzbfile"; filename="example.nzb"', body)
        self.assertIn(b"<nzb />", body)

    def test_download_route_is_rebased_to_configured_prowlarr_host(self) -> None:
        target, owned = _prowlarr_download_target(
            "https://prowlarr.home/prowlarr",
            "http://docker-host:9696/api/v1/indexer/7/download?link=abc",
            7,
        )

        self.assertTrue(owned)
        self.assertEqual(
            target,
            "https://prowlarr.home/prowlarr/api/v1/indexer/7/download?link=abc",
        )

    def test_external_indexer_url_is_not_rebased(self) -> None:
        target, owned = _prowlarr_download_target(
            "https://prowlarr.home", "https://indexer.test/get?nzb=1", 7
        )

        self.assertFalse(owned)
        self.assertEqual(target, "https://indexer.test/get?nzb=1")

    def test_sab_download_url_contains_prowlarr_query_key(self) -> None:
        client = ProwlarrClient(
            Settings(
                prowlarr_url="https://prowlarr.home/prowlarr",
                prowlarr_api_key="secret key",
            )
        )
        release = Release(
            title="Example",
            guid="example",
            indexer="ExampleNZB",
            indexer_id=7,
            download_url="http://docker:9696/api/v1/indexer/7/download?link=abc",
        )

        url = client.sab_download_url(release)

        self.assertIn("https://prowlarr.home/prowlarr/api/v1/indexer/7/download?", url)
        self.assertIn("link=abc", url)
        self.assertIn("apikey=secret+key", url)

    @patch("nzb_compass.api.urlopen")
    def test_search_sends_selected_indexer_ids(self, mocked_urlopen: object) -> None:
        mocked_urlopen.return_value = _JsonResponse(b"[]")
        client = ProwlarrClient(
            Settings(prowlarr_url="http://prowlarr.test", prowlarr_api_key="key")
        )

        self.assertEqual(client.search("example", [3, 9]), [])
        request = mocked_urlopen.call_args.args[0]
        self.assertIn("query=example", request.full_url)
        self.assertIn("indexerIds=3", request.full_url)
        self.assertIn("indexerIds=9", request.full_url)

    def test_sab_dashboard_combines_queue_and_history(self) -> None:
        client = SabnzbdClient(Settings())
        responses = [
            {
                "queue": {
                    "paused": False,
                    "status": "Downloading",
                    "speed": "12.4 MB/s",
                    "kbpersec": "1550.0",
                    "timeleft": "0:04:12",
                    "sizeleft": "2.1 GB",
                    "size": "4.0 GB",
                    "noofslots": 1,
                    "slots": [
                        {
                            "nzo_id": "SABnzbd_nzo_queue",
                            "filename": "Example",
                            "status": "Downloading",
                            "percentage": "48",
                            "size": "4.0 GB",
                            "timeleft": "0:04:12",
                        }
                    ],
                }
            },
            {
                "history": {
                    "slots": [
                        {
                            "nzo_id": "SABnzbd_nzo_history",
                            "name": "Finished",
                            "status": "Completed",
                            "size": "1.0 GB",
                        }
                    ]
                }
            },
        ]

        with patch.object(SabnzbdClient, "_request", side_effect=responses):
            dashboard = client.dashboard()

        self.assertEqual(dashboard.speed, "12.4 MB/s")
        self.assertEqual(dashboard.bandwidth_mbps, 12.4)
        self.assertEqual(dashboard.bandwidth_label, "12.4 Mbps")
        self.assertEqual(dashboard.queue_count, 1)
        self.assertEqual(dashboard.history_count, 1)
        self.assertEqual(dashboard.queue[0].nzo_id, "SABnzbd_nzo_queue")
        self.assertEqual(dashboard.queue[0].percentage, 48)
        self.assertEqual(dashboard.history[0].nzo_id, "SABnzbd_nzo_history")
        self.assertEqual(dashboard.history[0].status, "Completed")

    def test_sab_failed_history_includes_normalized_reason(self) -> None:
        client = SabnzbdClient(Settings())
        responses = [
            {"queue": {"slots": []}},
            {
                "history": {
                    "slots": [
                        {
                            "nzo_id": "SABnzbd_nzo_failed",
                            "name": "Broken download",
                            "status": "Failed",
                            "fail_message": "  Unpacking failed:\n disk is full  ",
                        }
                    ]
                }
            },
        ]

        with patch.object(SabnzbdClient, "_request", side_effect=responses):
            item = client.dashboard().history[0]

        self.assertEqual(item.failure_reason, "Unpacking failed: disk is full")
        self.assertEqual(
            item.failure_description, "Reason: Unpacking failed: disk is full"
        )

    def test_sab_categories_are_parsed(self) -> None:
        client = SabnzbdClient(Settings())
        with patch.object(
            SabnzbdClient,
            "_request",
            return_value={"categories": ["*", "movies", "tv"]},
        ):
            self.assertEqual(client.categories(), ["*", "movies", "tv"])

    def test_sab_add_url_applies_download_defaults(self) -> None:
        client = SabnzbdClient(
            Settings(
                sabnzbd_category="movies",
                sabnzbd_priority=1,
                sabnzbd_post_processing=3,
            )
        )
        with patch.object(
            SabnzbdClient,
            "_request",
            return_value={"status": True, "nzo_ids": ["SABnzbd_nzo_1"]},
        ) as request:
            identifier = client.add_url("https://prowlarr.test/download", "Example")

        self.assertEqual(identifier, "SABnzbd_nzo_1")
        params = request.call_args.args[0]
        self.assertEqual(params["cat"], "movies")
        self.assertEqual(params["priority"], "1")
        self.assertEqual(params["pp"], "3")

    def test_sab_job_actions_use_the_job_identifier(self) -> None:
        client = SabnzbdClient(Settings())
        with patch.object(
            SabnzbdClient, "_request", return_value={"status": True}
        ) as request:
            client.set_job_paused("SABnzbd_nzo_1", True)
            client.retry_history_job("SABnzbd_nzo_2")

        pause_params = request.call_args_list[0].args[0]
        retry_params = request.call_args_list[1].args[0]
        self.assertEqual(
            pause_params,
            {
                "mode": "queue",
                "name": "pause",
                "value": "SABnzbd_nzo_1",
                "output": "json",
            },
        )
        self.assertEqual(retry_params["mode"], "retry")
        self.assertEqual(retry_params["value"], "SABnzbd_nzo_2")
