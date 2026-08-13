from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(slots=True)
class Release:
    title: str
    guid: str
    download_url: str
    indexer: str
    indexer_id: int | None = None
    size: int = 0
    publish_date: datetime | None = None
    categories: list[str] = field(default_factory=list)
    category_ids: list[int] = field(default_factory=list)
    protocol: str = "usenet"
    age: int | None = None
    grabs: int | None = None
    files: int | None = None
    sub_group: str | None = None
    imdb_id: int | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    indexer_flags: list[str] = field(default_factory=list)
    info_url: str | None = None
    description: str | None = None

    @classmethod
    def from_prowlarr(cls, data: dict[str, Any]) -> "Release":
        categories = []
        category_ids = []
        for item in data.get("categories") or []:
            if isinstance(item, dict):
                label = item.get("name") or str(item.get("id", ""))
                if item.get("id") is not None:
                    category_ids.append(int(item["id"]))
            else:
                label = str(item)
            if label:
                categories.append(label)

        info_url = data.get("infoUrl") or data.get("details")
        return cls(
            title=data.get("title") or "Untitled release",
            guid=str(data.get("guid") or data.get("downloadUrl") or ""),
            download_url=data.get("downloadUrl") or "",
            indexer=data.get("indexer") or "Unknown indexer",
            indexer_id=data.get("indexerId"),
            size=int(data.get("size") or 0),
            publish_date=_parse_date(data.get("publishDate")),
            categories=categories,
            category_ids=category_ids,
            protocol=(data.get("protocol") or "usenet").lower(),
            age=data.get("age"),
            grabs=data.get("grabs"),
            files=data.get("files"),
            sub_group=data.get("subGroup"),
            imdb_id=data.get("imdbId") or None,
            tmdb_id=data.get("tmdbId") or None,
            tvdb_id=data.get("tvdbId") or None,
            indexer_flags=[str(flag) for flag in (data.get("indexerFlags") or [])],
            info_url=info_url,
            description=data.get("description"),
        )

    @property
    def size_label(self) -> str:
        size = float(self.size)
        units = ("B", "KB", "MB", "GB", "TB")
        unit = units[0]
        for unit in units:
            if size < 1024 or unit == units[-1]:
                break
            size /= 1024
        return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"

    @property
    def age_label(self) -> str:
        if self.publish_date:
            now = datetime.now(timezone.utc)
            published = self.publish_date
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            days = max(0, (now - published).days)
            if days == 0:
                return "Today"
            if days == 1:
                return "1 day ago"
            return f"{days} days ago"
        if self.age is not None:
            return f"{self.age} days ago"
        return "Unknown age"

    @property
    def content_type(self) -> str:
        names = " ".join(self.categories).lower()
        if (
            any(1000 <= category_id < 2000 for category_id in self.category_ids)
            or 4050 in self.category_ids
            or "game" in names
            or "console" in names
        ):
            return "Games"
        category_groups = {category_id // 1000 for category_id in self.category_ids}
        if 2 in category_groups or "movie" in names:
            return "Movies"
        if 5 in category_groups or names.startswith("tv") or " tv/" in names:
            return "TV"
        if 3 in category_groups or "audio" in names or "music" in names:
            return "Audio"
        if 7 in category_groups or "book" in names or "comic" in names:
            return "Books"
        if 4 in category_groups or "software" in names or names.startswith("pc"):
            return "Software"
        return "Other"


@dataclass(slots=True)
class QueueItem:
    name: str
    status: str
    percentage: float
    size: str = ""
    time_left: str = ""
    category: str = ""


@dataclass(slots=True)
class HistoryItem:
    name: str
    status: str
    size: str = ""
    category: str = ""
    completed: int | None = None

    @property
    def completed_label(self) -> str:
        if not self.completed:
            return ""
        completed_at = datetime.fromtimestamp(self.completed, tz=timezone.utc)
        now = datetime.now(timezone.utc)
        days = max(0, (now - completed_at).days)
        if days == 0:
            return completed_at.astimezone().strftime("Today at %H:%M")
        if days == 1:
            return "Yesterday"
        return completed_at.astimezone().strftime("%b %-d")


@dataclass(slots=True)
class SabDashboard:
    paused: bool
    status: str
    speed: str
    time_left: str
    size_left: str
    queue_size: str
    queue_count: int
    queue: list[QueueItem] = field(default_factory=list)
    history: list[HistoryItem] = field(default_factory=list)


@dataclass(slots=True)
class Indexer:
    id: int
    name: str
    protocol: str
    enabled_in_prowlarr: bool
    supports_search: bool
    privacy: str = ""
    priority: int = 25
    description: str = ""
    status_message: str = ""

    @classmethod
    def from_prowlarr(cls, data: dict[str, Any]) -> "Indexer":
        status = data.get("status") or {}
        message = status.get("message") if isinstance(status, dict) else ""
        return cls(
            id=int(data.get("id") or 0),
            name=data.get("name") or data.get("definitionName") or "Unnamed indexer",
            protocol=(data.get("protocol") or "unknown").lower(),
            enabled_in_prowlarr=bool(data.get("enable", False)),
            supports_search=bool(data.get("supportsSearch", False)),
            privacy=data.get("privacy") or "",
            priority=int(data.get("priority") or 25),
            description=data.get("description") or "",
            status_message=message or "",
        )
