from __future__ import annotations

import json
import mimetypes
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .config import Settings
from .models import HistoryItem, Indexer, QueueItem, Release, SabDashboard


class ApiError(RuntimeError):
    pass


def _friendly_error(exc: Exception, service: str) -> ApiError:
    if isinstance(exc, HTTPError):
        if exc.code in (401, 403):
            return ApiError(f"{service} rejected the API key.")
        try:
            body = exc.read().decode("utf-8", errors="replace")
            payload = json.loads(body)
            detail = payload.get("message") or payload.get("error")
            if detail:
                return ApiError(f"{service} returned HTTP {exc.code}: {detail}")
        except (OSError, ValueError, AttributeError):
            pass
        return ApiError(f"{service} returned HTTP {exc.code}.")
    if isinstance(exc, URLError):
        return ApiError(f"Could not connect to {service}: {exc.reason}")
    if isinstance(exc, TimeoutError):
        return ApiError(f"{service} did not respond in time.")
    return ApiError(f"{service} request failed: {exc}")


def _read_json(request: Request, service: str) -> Any:
    try:
        with urlopen(request, timeout=20) as response:
            return json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise _friendly_error(exc, service) from exc


def _api_url(base: str, path: str) -> str:
    return urljoin(base.rstrip("/") + "/", path.lstrip("/"))


@dataclass(slots=True)
class ProwlarrClient:
    settings: Settings

    def test(self) -> str:
        request = Request(
            _api_url(self.settings.prowlarr_url, "/api/v1/system/status"),
            headers={"X-Api-Key": self.settings.prowlarr_api_key, "Accept": "application/json"},
        )
        payload = _read_json(request, "Prowlarr")
        return str(payload.get("version") or "Connected")

    def indexers(self) -> list[Indexer]:
        request = Request(
            _api_url(self.settings.prowlarr_url, "/api/v1/indexer"),
            headers={"X-Api-Key": self.settings.prowlarr_api_key, "Accept": "application/json"},
        )
        payload = _read_json(request, "Prowlarr")
        if not isinstance(payload, list):
            raise ApiError("Prowlarr returned an unexpected indexer response.")
        indexers = [Indexer.from_prowlarr(item) for item in payload if isinstance(item, dict)]
        return sorted(
            [indexer for indexer in indexers if indexer.protocol == "usenet"],
            key=lambda indexer: (indexer.priority, indexer.name.lower()),
        )

    def search(self, query: str, indexer_ids: list[int] | None = None) -> list[Release]:
        values: list[tuple[str, str | int]] = [("query", query), ("type", "search")]
        values.extend(("indexerIds", indexer_id) for indexer_id in (indexer_ids or []))
        params = urlencode(values)
        request = Request(
            f"{_api_url(self.settings.prowlarr_url, '/api/v1/search')}?{params}",
            headers={"X-Api-Key": self.settings.prowlarr_api_key, "Accept": "application/json"},
        )
        payload = _read_json(request, "Prowlarr")
        if not isinstance(payload, list):
            raise ApiError("Prowlarr returned an unexpected search response.")
        releases = [Release.from_prowlarr(item) for item in payload if isinstance(item, dict)]
        return [release for release in releases if release.protocol == "usenet"]

    def download_nzb(self, release: Release) -> tuple[bytes, str]:
        if not release.download_url:
            raise ApiError("This release does not include a download link.")
        target, prowlarr_owned = _prowlarr_download_target(
            self.settings.prowlarr_url, release.download_url, release.indexer_id
        )
        parsed_target = urlparse(target)
        parsed_base = urlparse(self.settings.prowlarr_url)
        headers = {"Accept": "application/x-nzb, application/octet-stream"}
        if prowlarr_owned or parsed_target.netloc == parsed_base.netloc:
            headers["X-Api-Key"] = self.settings.prowlarr_api_key
        try:
            opener = build_opener(_SafeRedirectHandler())
            with opener.open(Request(target, headers=headers), timeout=30) as response:
                data = response.read()
                disposition = response.headers.get("Content-Disposition", "")
        except (HTTPError, URLError, TimeoutError) as exc:
            service = "Prowlarr"
            if isinstance(exc, HTTPError):
                failed_host = urlparse(exc.geturl()).netloc
                if failed_host and failed_host != parsed_base.netloc:
                    service = "The indexer"
            raise _friendly_error(exc, service) from exc
        if not data:
            raise ApiError("Prowlarr returned an empty NZB file.")
        filename = f"{release.title}.nzb"
        if "filename=" in disposition:
            filename = disposition.split("filename=", 1)[1].strip(' "')
        return data, filename

    def sab_download_url(self, release: Release) -> str:
        if not release.download_url:
            raise ApiError("This release does not include a download link.")
        target, prowlarr_owned = _prowlarr_download_target(
            self.settings.prowlarr_url, release.download_url, release.indexer_id
        )
        if not prowlarr_owned:
            return target
        parsed = urlparse(target)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["apikey"] = self.settings.prowlarr_api_key
        return urlunparse(parsed._replace(query=urlencode(query)))


@dataclass(slots=True)
class SabnzbdClient:
    settings: Settings

    def test(self) -> str:
        payload = self._request({"mode": "version", "output": "json"})
        return str(payload.get("version") or "Connected")

    def add_nzb(self, contents: bytes, filename: str) -> str:
        fields = {
            "mode": "addfile",
            "apikey": self.settings.sabnzbd_api_key,
            "output": "json",
        }
        if self.settings.sabnzbd_category:
            fields["cat"] = self.settings.sabnzbd_category
        body, content_type = _multipart(fields, "nzbfile", filename, contents)
        request = Request(
            _api_url(self.settings.sabnzbd_url, "/api"),
            data=body,
            headers={"Content-Type": content_type, "Accept": "application/json"},
            method="POST",
        )
        payload = _read_json(request, "SABnzbd")
        if not payload.get("status"):
            raise ApiError(str(payload.get("error") or "SABnzbd did not accept the NZB."))
        nzo_ids = payload.get("nzo_ids") or []
        return str(nzo_ids[0]) if nzo_ids else filename

    def add_url(self, download_url: str, title: str) -> str:
        values = {
            "mode": "addurl",
            "name": download_url,
            "nzbname": title,
            "output": "json",
        }
        if self.settings.sabnzbd_category:
            values["cat"] = self.settings.sabnzbd_category
        payload = self._request(values)
        if not payload.get("status"):
            raise ApiError(str(payload.get("error") or "SABnzbd did not accept the URL."))
        nzo_ids = payload.get("nzo_ids") or []
        return str(nzo_ids[0]) if nzo_ids else title

    def dashboard(self) -> SabDashboard:
        queue_payload = self._request({"mode": "queue", "output": "json"})
        history_payload = self._request(
            {"mode": "history", "limit": "20", "output": "json"}
        )
        queue_data = queue_payload.get("queue") or {}
        slots = queue_data.get("slots") or []
        queue = [
            QueueItem(
                name=slot.get("filename") or slot.get("name") or "Untitled download",
                status=slot.get("status") or "Queued",
                percentage=float(slot.get("percentage") or 0),
                size=slot.get("size") or "",
                time_left=slot.get("timeleft") or "",
                category=slot.get("cat") or slot.get("category") or "",
            )
            for slot in slots
        ]
        history_data = history_payload.get("history") or {}
        history = [
            HistoryItem(
                name=slot.get("name") or slot.get("nzb_name") or "Untitled download",
                status=slot.get("status") or "Unknown",
                size=slot.get("size") or "",
                category=slot.get("category") or slot.get("cat") or "",
                completed=int(slot.get("completed") or 0) or None,
            )
            for slot in (history_data.get("slots") or [])
        ]
        return SabDashboard(
            paused=bool(queue_data.get("paused", False)),
            status=queue_data.get("status") or "Idle",
            speed=queue_data.get("speed") or "0 B/s",
            time_left=queue_data.get("timeleft") or "0:00:00",
            size_left=queue_data.get("sizeleft") or "0 B",
            queue_size=queue_data.get("size") or "0 B",
            queue_count=int(queue_data.get("noofslots") or len(queue)),
            queue=queue,
            history=history,
        )

    def set_paused(self, paused: bool) -> None:
        mode = "pause" if paused else "resume"
        payload = self._request({"mode": mode, "output": "json"})
        if payload.get("status") is False:
            raise ApiError(f"SABnzbd could not {mode} the queue.")

    def _request(self, params: dict[str, str]) -> dict[str, Any]:
        values = {**params, "apikey": self.settings.sabnzbd_api_key}
        request = Request(f"{_api_url(self.settings.sabnzbd_url, '/api')}?{urlencode(values)}")
        payload = _read_json(request, "SABnzbd")
        if not isinstance(payload, dict):
            raise ApiError("SABnzbd returned an unexpected response.")
        return payload


def _multipart(
    fields: dict[str, str], file_field: str, filename: str, contents: bytes
) -> tuple[bytes, str]:
    boundary = f"----nzb-compass-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    safe_filename = filename.replace('"', "'").replace("\r", "").replace("\n", "")
    mime = mimetypes.guess_type(safe_filename)[0] or "application/x-nzb"
    chunks.extend(
        [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{file_field}"; filename="{safe_filename}"\r\n'.encode(),
            f"Content-Type: {mime}\r\n\r\n".encode(),
            contents,
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _prowlarr_download_target(
    base_url: str, download_url: str, indexer_id: int | None
) -> tuple[str, bool]:
    """Return a configured-host URL for routes that are owned by Prowlarr."""
    parsed_base = urlparse(base_url)
    parsed_target = urlparse(download_url)
    if not parsed_target.scheme:
        return _api_url(base_url, download_url), True

    marker = "/api/v1/indexer/"
    marker_position = parsed_target.path.find(marker)
    route = parsed_target.path[marker_position:] if marker_position >= 0 else ""
    if not route and indexer_id is not None:
        legacy_route = f"/{indexer_id}/download"
        if parsed_target.path.endswith(legacy_route):
            route = legacy_route
    if route:
        base_path = parsed_base.path.rstrip("/")
        path = f"{base_path}{route}"
        return (
            urlunparse(
                (
                    parsed_base.scheme,
                    parsed_base.netloc,
                    path,
                    "",
                    parsed_target.query,
                    "",
                )
            ),
            True,
        )
    return download_url, parsed_target.netloc == parsed_base.netloc


class _SafeRedirectHandler(HTTPRedirectHandler):
    """Prevent a Prowlarr API key from following a redirect to an indexer."""

    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Request | None:
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected and urlparse(req.full_url).netloc != urlparse(newurl).netloc:
            redirected.remove_header("X-Api-Key")
        return redirected
