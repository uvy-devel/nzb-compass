from __future__ import annotations

import html
import sys
import threading
import webbrowser
from collections.abc import Callable
from typing import Any

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gio, GLib, Gtk  # noqa: E402

from .api import ApiError, ProwlarrClient, SabnzbdClient
from .config import Settings
from .models import HistoryItem, Indexer, QueueItem, Release, SabDashboard


APP_ID = "io.github.uvy-devel.NzbCompass"
SAB_PRIORITIES = [
    ("Default (category)", -100),
    ("Paused", -2),
    ("Low", -1),
    ("Normal", 0),
    ("High", 1),
    ("Force", 2),
]
SAB_POST_PROCESSING = [
    ("Default (category)", -1),
    ("None", 0),
    ("Repair", 1),
    ("Repair and unpack", 2),
    ("Repair, unpack, and delete", 3),
]


def _async(
    work: Callable[[], Any],
    success: Callable[[Any], None],
    failure: Callable[[Exception], None],
) -> None:
    def run() -> None:
        try:
            result = work()
        except Exception as exc:  # UI boundary: errors must reach the main loop.
            GLib.idle_add(failure, exc)
        else:
            GLib.idle_add(success, result)

    threading.Thread(target=run, daemon=True).start()


class NzbCompassApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS)
        self.connect("activate", self._on_activate)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        provider = Gtk.CssProvider()
        provider.load_from_string(CSS)
        display = Gdk.Display.get_default()
        if display:
            Gtk.StyleContext.add_provider_for_display(
                display, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
            )
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<primary>q"])

    def _on_activate(self, _app: Adw.Application) -> None:
        window = self.get_active_window()
        if not window:
            window = MainWindow(self)
        window.present()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: NzbCompassApplication) -> None:
        super().__init__(application=app, title="NZB Compass")
        self.set_default_size(1080, 720)
        self.set_size_request(640, 520)
        self.settings = Settings.load()
        self.releases: list[Release] = []
        self.indexers: list[Indexer] = []
        self._sab_refreshing = False
        self._sab_refresh_timer: int | None = None
        self._sab_paused = False
        self._build_ui()
        if not self.settings.prowlarr_api_key or not self.settings.sabnzbd_api_key:
            GLib.idle_add(self.open_settings, True)

    def _build_ui(self) -> None:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()

        title = Adw.WindowTitle(title="NZB Compass", subtitle="Prowlarr + SABnzbd")
        header.set_title_widget(title)

        settings_button = Gtk.Button(icon_name="preferences-system-symbolic", tooltip_text="Settings")
        settings_button.connect("clicked", lambda *_: self.open_settings())
        header.pack_end(settings_button)
        toolbar.add_top_bar(header)

        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.add_css_class("app-background")

        switcher = Gtk.StackSwitcher()
        switcher.set_halign(Gtk.Align.CENTER)
        switcher.set_margin_top(12)
        switcher.set_margin_bottom(8)
        switcher.add_css_class("pill")
        root.append(switcher)

        self.stack = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_vexpand(True)
        switcher.set_stack(self.stack)
        self.stack.add_titled(self._search_page(), "search", "Search")
        self.stack.add_titled(self._indexers_page(), "indexers", "Indexers")
        self.stack.add_titled(self._queue_page(), "queue", "SABnzbd")
        self.stack.connect("notify::visible-child-name", self._page_changed)
        root.append(self.stack)

        self.toast_overlay = Adw.ToastOverlay(child=root)
        toolbar.set_content(self.toast_overlay)
        self.set_content(toolbar)

    def _search_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        page.set_margin_start(28)
        page.set_margin_end(28)
        page.set_margin_top(16)
        page.set_margin_bottom(24)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        hero.set_halign(Gtk.Align.CENTER)
        heading = Gtk.Label(label="Find your next release")
        heading.add_css_class("hero-title")
        subtitle = Gtk.Label(label="Search every enabled Usenet indexer in Prowlarr")
        subtitle.add_css_class("dim-label")
        hero.append(heading)
        hero.append(subtitle)
        page.append(hero)

        search_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        search_box.set_hexpand(True)
        self.search_entry = Gtk.SearchEntry(placeholder_text="Movie, series, game, book…")
        self.search_entry.set_size_request(260, -1)
        self.search_entry.set_hexpand(True)
        self.search_entry.connect("activate", self._start_search)
        search_button = Gtk.Button(label="Search")
        search_button.add_css_class("suggested-action")
        search_button.add_css_class("search-button")
        search_button.connect("clicked", self._start_search)
        self.search_button = search_button
        search_box.append(self.search_entry)
        search_box.append(search_button)
        search_clamp = Adw.Clamp()
        search_clamp.set_maximum_size(650)
        search_clamp.set_child(search_box)
        page.append(search_clamp)

        filter_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        filter_bar.set_halign(Gtk.Align.CENTER)
        type_label = Gtk.Label(label="Type")
        type_label.add_css_class("dim-label")
        self.content_types = [
            "All results",
            "Games",
            "Movies",
            "TV",
            "Audio",
            "Books",
            "Software",
            "Other",
        ]
        self.type_dropdown = Gtk.DropDown.new_from_strings(self.content_types)
        self.type_dropdown.connect("notify::selected", lambda *_: self._render_results())
        indexer_label = Gtk.Label(label="Indexer")
        indexer_label.add_css_class("dim-label")
        self.indexer_filter_names = ["All indexers"]
        self.indexer_dropdown = Gtk.DropDown.new_from_strings(self.indexer_filter_names)
        self.indexer_dropdown.connect("notify::selected", lambda *_: self._render_results())
        sort_label = Gtk.Label(label="Sort")
        sort_label.add_css_class("dim-label")
        self.sort_dropdown = Gtk.DropDown.new_from_strings(["Newest", "Largest", "Smallest", "Indexer"])
        self.sort_dropdown.connect("notify::selected", lambda *_: self._render_results())
        filter_bar.append(type_label)
        filter_bar.append(self.type_dropdown)
        filter_bar.append(indexer_label)
        filter_bar.append(self.indexer_dropdown)
        filter_bar.append(sort_label)
        filter_bar.append(self.sort_dropdown)
        page.append(filter_bar)

        self.results_summary = Gtk.Label(label="", xalign=0)
        self.results_summary.add_css_class("dim-label")
        self.results_summary.set_halign(Gtk.Align.CENTER)
        page.append(self.results_summary)

        self.search_status = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.search_status.set_vexpand(True)
        self.search_status.add_named(self._empty_state(), "empty")

        spinner_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        spinner_box.set_valign(Gtk.Align.CENTER)
        spinner = Gtk.Spinner(spinning=True)
        spinner.set_size_request(36, 36)
        spinner_box.append(spinner)
        self.search_spinner_label = Gtk.Label(label="Loading available indexers…")
        spinner_box.append(self.search_spinner_label)
        self.search_status.add_named(spinner_box, "loading")

        no_matches = Adw.StatusPage()
        no_matches.set_icon_name("edit-find-symbolic")
        no_matches.set_title("No results match these filters")
        no_matches.set_description("Try another content type or indexer.")
        self.search_status.add_named(no_matches, "no_matches")

        self.results_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.results_list.add_css_class("boxed-list")
        results_scroll = Gtk.ScrolledWindow(vexpand=True)
        results_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        results_scroll.set_child(self.results_list)
        self.search_status.add_named(results_scroll, "results")
        page.append(self.search_status)
        return page

    def _indexers_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_margin_start(28)
        page.set_margin_end(28)
        page.set_margin_top(16)
        page.set_margin_bottom(24)

        heading_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        heading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        heading_box.set_hexpand(True)
        heading = Gtk.Label(label="Usenet indexers", xalign=0)
        heading.add_css_class("title-2")
        self.indexer_summary = Gtk.Label(
            label="Loading indexers configured in Prowlarr…", xalign=0
        )
        self.indexer_summary.add_css_class("dim-label")
        heading_box.append(heading)
        heading_box.append(self.indexer_summary)
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh indexers")
        refresh.connect("clicked", lambda *_: self.refresh_indexers())
        heading_row.append(heading_box)
        heading_row.append(refresh)
        page.append(heading_row)

        note = Gtk.Label(
            label="These switches control which indexers NZB Compass searches. They do not change your Prowlarr configuration.",
            xalign=0,
            wrap=True,
        )
        note.add_css_class("dim-label")
        page.append(note)

        self.indexer_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.indexer_list.add_css_class("boxed-list")
        self.indexer_status = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.indexer_status.set_vexpand(True)
        loading = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        loading.set_valign(Gtk.Align.CENTER)
        indexer_spinner = Gtk.Spinner(spinning=True)
        indexer_spinner.set_size_request(36, 36)
        loading.append(indexer_spinner)
        loading.append(Gtk.Label(label="Reading indexers from Prowlarr…"))
        self.indexer_status.add_named(loading, "loading")
        empty = Adw.StatusPage()
        empty.set_icon_name("network-offline-symbolic")
        empty.set_title("No Usenet indexers found")
        empty.set_description(
            "Add and enable a Usenet indexer in Prowlarr, then refresh this page."
        )
        self.indexer_status.add_named(empty, "empty")
        scroll = Gtk.ScrolledWindow(vexpand=True)
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scroll.set_child(self.indexer_list)
        self.indexer_status.add_named(scroll, "items")
        page.append(self.indexer_status)
        return page

    def _empty_state(self) -> Gtk.Widget:
        status = Adw.StatusPage()
        status.set_icon_name("system-search-symbolic")
        status.set_title("Search across your indexers")
        status.set_description("Results include size, age, categories, source, and release details.")
        return status

    def _queue_page(self) -> Gtk.Widget:
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer.set_margin_start(18)
        outer.set_margin_end(18)
        outer.set_margin_top(16)
        outer.set_margin_bottom(24)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(1120)
        clamp.set_tightening_threshold(900)
        clamp.set_vexpand(True)

        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        page.set_vexpand(True)
        page.add_css_class("sab-dashboard")

        heading_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        heading_row.add_css_class("sab-header-card")
        sab_icon = Gtk.Image.new_from_icon_name("folder-download-symbolic")
        sab_icon.set_pixel_size(26)
        sab_icon.add_css_class("sab-brand-icon")
        heading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        heading_box.set_hexpand(True)
        heading = Gtk.Label(label="SABnzbd Dashboard", xalign=0)
        heading.add_css_class("title-2")
        heading.set_ellipsize(3)
        self.sab_state_label = Gtk.Label(label="Connecting…", xalign=0)
        self.sab_state_label.add_css_class("sab-state")
        self.sab_state_label.set_ellipsize(3)
        heading_box.append(heading)
        heading_box.append(self.sab_state_label)
        controls = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        controls.add_css_class("linked")
        self.sab_pause_button = Gtk.Button(
            icon_name="media-playback-pause-symbolic", tooltip_text="Pause downloads"
        )
        self.sab_pause_button.connect("clicked", self._toggle_sab_pause)
        open_sab = Gtk.Button(icon_name="web-browser-symbolic", tooltip_text="Open SABnzbd")
        open_sab.connect("clicked", lambda *_: webbrowser.open(self.settings.sabnzbd_url))
        refresh = Gtk.Button(icon_name="view-refresh-symbolic", tooltip_text="Refresh dashboard")
        refresh.connect("clicked", lambda *_: self.refresh_queue())
        controls.append(self.sab_pause_button)
        controls.append(refresh)
        controls.append(open_sab)
        heading_row.append(sab_icon)
        heading_row.append(heading_box)
        heading_row.append(controls)
        page.append(heading_row)

        stats = Gtk.Grid()
        stats.set_column_homogeneous(True)
        stats.set_column_spacing(10)
        stats.add_css_class("sab-stats")
        self._sab_stat_icons: list[Gtk.Image] = []
        self.sab_speed_value = self._stat_card(
            stats,
            0,
            "Bandwidth",
            "0 B/s  •  0 Mbps",
            "network-transmit-receive-symbolic",
        )
        self.sab_remaining_value = self._stat_card(
            stats, 1, "Remaining", "0 B", "drive-harddisk-symbolic"
        )
        self.sab_time_value = self._stat_card(
            stats, 2, "Time left", "0:00:00", "alarm-symbolic"
        )
        self.sab_jobs_value = self._stat_card(
            stats, 3, "Queue size", "0 jobs", "view-list-symbolic"
        )
        page.append(stats)

        section_switcher = Gtk.StackSwitcher()
        section_switcher.set_halign(Gtk.Align.CENTER)
        section_switcher.add_css_class("pill")
        page.append(section_switcher)
        self.sab_sections = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.sab_sections.set_vexpand(True)
        section_switcher.set_stack(self.sab_sections)

        self.queue_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.queue_list.add_css_class("boxed-list")
        self.queue_list.add_css_class("sab-job-list")
        self.queue_status = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        self.queue_status.set_vexpand(True)
        queue_empty = Adw.StatusPage()
        queue_empty.set_icon_name("folder-download-symbolic")
        queue_empty.set_title("Nothing downloading")
        queue_empty.set_description("Releases sent to SABnzbd will appear here.")
        self.queue_status.add_named(queue_empty, "empty")
        queue_scroll = Gtk.ScrolledWindow(vexpand=True)
        queue_scroll.set_child(self.queue_list)
        self.queue_status.add_named(queue_scroll, "items")
        self.sab_queue_page = self.sab_sections.add_titled(
            self.queue_status, "active", "Queue · 0"
        )

        self.history_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.history_list.add_css_class("boxed-list")
        self.history_list.add_css_class("sab-job-list")
        self.history_status = Gtk.Stack(transition_type=Gtk.StackTransitionType.CROSSFADE)
        history_empty = Adw.StatusPage()
        history_empty.set_icon_name("document-open-recent-symbolic")
        history_empty.set_title("No recent history")
        history_empty.set_description("Completed and failed jobs will appear here.")
        self.history_status.add_named(history_empty, "empty")
        history_scroll = Gtk.ScrolledWindow(vexpand=True)
        history_scroll.set_child(self.history_list)
        self.history_status.add_named(history_scroll, "items")
        self.sab_history_page = self.sab_sections.add_titled(
            self.history_status, "history", "History · 0"
        )
        page.append(self.sab_sections)
        clamp.set_child(page)
        outer.append(clamp)

        compact = Adw.Breakpoint.new(
            Adw.BreakpointCondition.parse("max-width: 760sp")
        )
        compact.add_setter(outer, "margin-start", 10)
        compact.add_setter(outer, "margin-end", 10)
        compact.add_setter(heading_row, "spacing", 8)
        compact.add_setter(heading, "label", "SABnzbd")
        compact.add_setter(sab_icon, "visible", False)
        for stat_icon in self._sab_stat_icons:
            compact.add_setter(stat_icon, "visible", False)
        self.add_breakpoint(compact)
        return outer

    def _stat_card(
        self,
        parent: Gtk.Grid,
        column: int,
        title: str,
        value: str,
        icon_name: str,
    ) -> Gtk.Label:
        card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        card.set_hexpand(True)
        card.set_margin_start(10)
        card.set_margin_end(10)
        card.set_margin_top(10)
        card.set_margin_bottom(10)
        card.add_css_class("stat-card")
        icon = Gtk.Image.new_from_icon_name(icon_name)
        icon.set_pixel_size(20)
        icon.add_css_class("accent")
        self._sab_stat_icons.append(icon)
        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        labels.set_hexpand(True)
        caption = Gtk.Label(label=title, xalign=0)
        caption.add_css_class("dim-label")
        value_label = Gtk.Label(label=value, xalign=0)
        value_label.add_css_class("heading")
        value_label.set_ellipsize(3)
        value_label.set_tooltip_text(value)
        labels.append(caption)
        labels.append(value_label)
        card.append(icon)
        card.append(labels)
        parent.attach(card, column, 0, 1, 1)
        return value_label

    def _start_search(self, *_args: object) -> None:
        query = self.search_entry.get_text().strip()
        if not query:
            self.search_entry.grab_focus()
            return
        if not self.settings.prowlarr_api_key:
            self._toast("Add your Prowlarr API key in Settings first")
            self.open_settings()
            return
        self.search_button.set_sensitive(False)
        self.search_status.set_visible_child_name("loading")
        self.search_spinner_label.set_label("Loading available indexers…")
        client = ProwlarrClient(self.settings)

        def work() -> tuple[list[Indexer], list[Release]]:
            indexers = client.indexers()
            active = self._active_indexers(indexers)
            if not active:
                raise ApiError(
                    "No searchable Usenet indexers are enabled. Check the Indexers page."
                )
            GLib.idle_add(
                self.search_spinner_label.set_label,
                f"Searching {len(active)} Usenet indexer{'s' if len(active) != 1 else ''}…",
            )
            return indexers, client.search(query, [indexer.id for indexer in active])

        _async(work, self._search_with_indexers_complete, self._request_failed)

    def _active_indexers(self, indexers: list[Indexer] | None = None) -> list[Indexer]:
        disabled = set(self.settings.disabled_indexer_ids)
        return [
            indexer
            for indexer in (indexers if indexers is not None else self.indexers)
            if indexer.enabled_in_prowlarr
            and indexer.supports_search
            and indexer.id not in disabled
        ]

    def _search_with_indexers_complete(
        self, result: tuple[list[Indexer], list[Release]]
    ) -> None:
        indexers, releases = result
        self.indexers = indexers
        self._render_indexers()
        self._search_complete(releases)

    def _search_complete(self, releases: list[Release]) -> None:
        self.search_button.set_sensitive(True)
        self.releases = releases
        self.type_dropdown.set_selected(0)
        self.indexer_filter_names = ["All indexers"] + sorted(
            {release.indexer for release in releases}, key=str.lower
        )
        self.indexer_dropdown.set_model(Gtk.StringList.new(self.indexer_filter_names))
        self.indexer_dropdown.set_selected(0)
        self._render_results()
        if not releases:
            self.search_status.set_visible_child_name("empty")
            self._toast("No Usenet results found")

    def _render_results(self) -> None:
        while child := self.results_list.get_first_child():
            self.results_list.remove(child)
        releases = list(self.releases)
        type_index = self.type_dropdown.get_selected()
        if type_index > 0 and type_index < len(self.content_types):
            selected_type = self.content_types[type_index]
            releases = [
                release for release in releases if release.content_type == selected_type
            ]
        indexer_index = self.indexer_dropdown.get_selected()
        if indexer_index > 0 and indexer_index < len(self.indexer_filter_names):
            selected_indexer = self.indexer_filter_names[indexer_index]
            releases = [
                release for release in releases if release.indexer == selected_indexer
            ]
        selected = self.sort_dropdown.get_selected()
        if selected == 0:
            releases.sort(key=lambda r: r.publish_date.timestamp() if r.publish_date else 0, reverse=True)
        elif selected == 1:
            releases.sort(key=lambda r: r.size, reverse=True)
        elif selected == 2:
            releases.sort(key=lambda r: r.size)
        else:
            releases.sort(key=lambda r: r.indexer.lower())
        for release in releases:
            self.results_list.append(self._release_row(release))
        if releases:
            self.search_status.set_visible_child_name("results")
        elif self.releases:
            self.search_status.set_visible_child_name("no_matches")
        self.results_summary.set_label(
            f"Showing {len(releases)} of {len(self.releases)} result{'s' if len(self.releases) != 1 else ''}"
            if self.releases
            else ""
        )

    def _release_row(self, release: Release) -> Gtk.Widget:
        row = Gtk.ListBoxRow(activatable=True)
        row.connect("activate", lambda *_: self.show_release(release))
        content = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        content.set_margin_start(16)
        content.set_margin_end(14)
        content.set_margin_top(13)
        content.set_margin_bottom(13)

        icon_box = Gtk.Box()
        icon_box.set_size_request(46, 46)
        icon_box.set_halign(Gtk.Align.CENTER)
        icon_box.set_valign(Gtk.Align.CENTER)
        icon_box.add_css_class("release-icon")
        icon = Gtk.Image.new_from_icon_name("package-x-generic-symbolic")
        icon.set_pixel_size(24)
        icon_box.append(icon)
        content.append(icon_box)

        labels = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        labels.set_hexpand(True)
        title = Gtk.Label(label=release.title, xalign=0, ellipsize=3)
        title.add_css_class("heading")
        title.set_tooltip_text(release.title)
        meta = Gtk.Label(
            label=f"{release.indexer}  •  {release.size_label}  •  {release.age_label}",
            xalign=0,
        )
        meta.add_css_class("dim-label")
        meta.set_ellipsize(3)
        labels.append(title)
        labels.append(meta)
        if release.categories:
            category = Gtk.Label(label="  •  ".join(release.categories[:3]), xalign=0)
            category.add_css_class("category-label")
            category.set_ellipsize(3)
            labels.append(category)
        content.append(labels)

        download = Gtk.Button(icon_name="folder-download-symbolic", tooltip_text="Send to SABnzbd")
        download.set_valign(Gtk.Align.CENTER)
        download.add_css_class("suggested-action")
        download.connect("clicked", lambda *_: self.download_release(release, download))
        content.append(download)
        chevron = Gtk.Image.new_from_icon_name("go-next-symbolic")
        chevron.add_css_class("dim-label")
        content.append(chevron)
        row.set_child(content)
        return row

    def show_release(self, release: Release) -> None:
        dialog = Gtk.Window(title="Release details", transient_for=self, modal=True)
        dialog.set_default_size(660, 480)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        header = Gtk.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Release details", subtitle=release.indexer))
        root.append(header)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_start(26)
        content.set_margin_end(26)
        content.set_margin_top(24)
        content.set_margin_bottom(26)
        title = Gtk.Label(label=release.title, xalign=0, wrap=True)
        title.add_css_class("title-2")
        content.append(title)

        group = Adw.PreferencesGroup(title="Release information")
        details = [
            ("Content type", release.content_type),
            ("Indexer", release.indexer),
            ("Size", release.size_label),
            ("Published", release.age_label),
            ("Protocol", release.protocol.title()),
            ("Categories", ", ".join(release.categories) or "Uncategorized"),
        ]
        if release.grabs is not None:
            details.append(("Grabs", str(release.grabs)))
        if release.files is not None:
            details.append(("Files", str(release.files)))
        if release.sub_group:
            details.append(("Release group", release.sub_group))
        identifiers = [
            f"IMDb {release.imdb_id}" if release.imdb_id else "",
            f"TMDB {release.tmdb_id}" if release.tmdb_id else "",
            f"TVDB {release.tvdb_id}" if release.tvdb_id else "",
        ]
        identifiers = [value for value in identifiers if value]
        if identifiers:
            details.append(("Database IDs", "  •  ".join(identifiers)))
        if release.indexer_flags:
            details.append(("Indexer flags", ", ".join(release.indexer_flags)))
        for label, value in details:
            item = Adw.ActionRow(title=label, subtitle=value)
            item.set_subtitle_selectable(True)
            group.add(item)
        content.append(group)

        if release.description:
            description = Gtk.Label(
                label=html.unescape(release.description), xalign=0, wrap=True, selectable=True
            )
            description.add_css_class("dim-label")
            content.append(description)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions.set_halign(Gtk.Align.END)
        if release.info_url:
            info = Gtk.Button(label="Open source page")
            info.connect("clicked", lambda *_: webbrowser.open(release.info_url or ""))
            actions.append(info)
        download = Gtk.Button(label="Send to SABnzbd")
        download.add_css_class("suggested-action")
        download.connect("clicked", lambda *_: self.download_release(release, download))
        actions.append(download)
        content.append(actions)
        scroll.set_child(content)
        root.append(scroll)
        dialog.set_child(root)
        dialog.present()

    def download_release(self, release: Release, button: Gtk.Button) -> None:
        if not self.settings.sabnzbd_api_key:
            self._toast("Add your SABnzbd API key in Settings first")
            self.open_settings()
            return
        button.set_sensitive(False)
        button.set_icon_name("content-loading-symbolic")

        def work() -> str:
            download_url = ProwlarrClient(self.settings).sab_download_url(release)
            return SabnzbdClient(self.settings).add_url(download_url, release.title)

        def done(_identifier: str) -> None:
            button.set_sensitive(True)
            button.set_icon_name("object-select-symbolic")
            self._toast(f"Sent “{release.title}” to SABnzbd")
            GLib.timeout_add_seconds(2, self.refresh_queue)

        def failed(exc: Exception) -> None:
            button.set_sensitive(True)
            button.set_icon_name("folder-download-symbolic")
            self._request_failed(exc)

        _async(work, done, failed)

    def _page_changed(self, *_args: object) -> None:
        page = self.stack.get_visible_child_name()
        if page == "queue":
            self.refresh_queue()
            if self._sab_refresh_timer is None:
                self._sab_refresh_timer = GLib.timeout_add_seconds(
                    5, self._auto_refresh_sab
                )
        elif page == "indexers":
            self.refresh_indexers()

    def refresh_indexers(self) -> bool:
        if not self.settings.prowlarr_api_key:
            self.indexer_summary.set_label("Add your Prowlarr connection in Settings first")
            return False
        self.indexer_status.set_visible_child_name("loading")
        _async(
            ProwlarrClient(self.settings).indexers,
            self._indexers_complete,
            self._indexers_failed,
        )
        return False

    def _indexers_complete(self, indexers: list[Indexer]) -> None:
        self.indexers = indexers
        self._render_indexers()

    def _indexers_failed(self, exc: Exception) -> None:
        self.indexer_summary.set_label(str(exc))
        self.indexer_status.set_visible_child_name("empty")
        self._request_failed(exc)

    def _render_indexers(self) -> None:
        while child := self.indexer_list.get_first_child():
            self.indexer_list.remove(child)
        disabled = set(self.settings.disabled_indexer_ids)
        active_count = 0
        for indexer in self.indexers:
            available = indexer.enabled_in_prowlarr and indexer.supports_search
            selected = available and indexer.id not in disabled
            if selected:
                active_count += 1
            state_parts = [indexer.privacy.title() if indexer.privacy else "Usenet"]
            state_parts.append(f"Priority {indexer.priority}")
            if not indexer.enabled_in_prowlarr:
                state_parts.append("Disabled in Prowlarr")
            elif not indexer.supports_search:
                state_parts.append("Does not support search")
            elif indexer.status_message:
                state_parts.append(indexer.status_message)
            else:
                state_parts.append("Ready")
            row = Adw.ActionRow(
                title=indexer.name,
                subtitle="  •  ".join(state_parts),
            )
            switch = Gtk.Switch(active=selected)
            switch.set_valign(Gtk.Align.CENTER)
            switch.set_sensitive(available)
            switch.set_tooltip_text(
                "Include in searches" if available else "Enable this indexer in Prowlarr first"
            )
            switch.connect("notify::active", self._indexer_toggled, indexer.id)
            row.add_suffix(switch)
            row.set_activatable_widget(switch)
            self.indexer_list.append(row)
        total = len(self.indexers)
        self.indexer_summary.set_label(
            f"{active_count} of {total} Usenet indexer{'s' if total != 1 else ''} selected for search"
        )
        self.indexer_status.set_visible_child_name("items" if self.indexers else "empty")

    def _indexer_toggled(
        self, switch: Gtk.Switch, _param: object, indexer_id: int
    ) -> None:
        disabled = set(self.settings.disabled_indexer_ids)
        if switch.get_active():
            disabled.discard(indexer_id)
        else:
            disabled.add(indexer_id)
        self.settings.disabled_indexer_ids = sorted(disabled)
        self.settings.save()
        active_count = len(self._active_indexers())
        total = len(self.indexers)
        self.indexer_summary.set_label(
            f"{active_count} of {total} Usenet indexer{'s' if total != 1 else ''} selected for search"
        )

    def refresh_queue(self) -> bool:
        if not self.settings.sabnzbd_api_key or self._sab_refreshing:
            return False
        self._sab_refreshing = True
        _async(
            SabnzbdClient(self.settings).dashboard,
            self._dashboard_complete,
            self._dashboard_failed,
        )
        return False

    def _auto_refresh_sab(self) -> bool:
        if self.stack.get_visible_child_name() == "queue":
            self.refresh_queue()
        return True

    def _dashboard_complete(self, dashboard: SabDashboard) -> None:
        self._sab_refreshing = False
        self._sab_paused = dashboard.paused
        self.sab_state_label.set_label(
            "Paused" if dashboard.paused else dashboard.status
        )
        self.sab_pause_button.set_icon_name(
            "media-playback-start-symbolic"
            if dashboard.paused
            else "media-playback-pause-symbolic"
        )
        self.sab_pause_button.set_tooltip_text(
            "Resume downloads" if dashboard.paused else "Pause downloads"
        )
        bandwidth = f"{dashboard.speed}  •  {dashboard.bandwidth_label}"
        self.sab_speed_value.set_label(bandwidth)
        self.sab_speed_value.set_tooltip_text(bandwidth)
        remaining = dashboard.size_left
        if dashboard.queue_size and dashboard.queue_size != dashboard.size_left:
            remaining = f"{dashboard.size_left} / {dashboard.queue_size}"
        self.sab_remaining_value.set_label(remaining)
        self.sab_time_value.set_label(dashboard.time_left)
        self.sab_jobs_value.set_label(
            f"{dashboard.queue_count} job{'s' if dashboard.queue_count != 1 else ''}"
        )
        self.sab_queue_page.set_title(f"Queue · {dashboard.queue_count}")
        self.sab_history_page.set_title(f"History · {dashboard.history_count}")
        self._render_queue(dashboard.queue)
        self._render_history(dashboard.history)

    def _dashboard_failed(self, exc: Exception) -> None:
        self._sab_refreshing = False
        self.sab_state_label.set_label("Connection error")
        self._request_failed(exc)

    def _render_queue(self, items: list[QueueItem]) -> None:
        while child := self.queue_list.get_first_child():
            self.queue_list.remove(child)
        for item in items:
            details = [item.size]
            if item.time_left:
                details.append(f"{item.time_left} left")
            if item.category:
                details.append(item.category)
            row = Adw.ActionRow(title=item.name, subtitle="  •  ".join(details))
            row.set_title_lines(1)
            row.set_subtitle_lines(1)
            status = Gtk.Label(label=item.status)
            status.add_css_class("sab-status-pill")
            if item.status.lower() in {"paused", "failed"}:
                status.add_css_class(f"sab-status-{item.status.lower()}")
            status.set_valign(Gtk.Align.CENTER)
            row.add_suffix(status)
            progress = Gtk.ProgressBar(fraction=max(0, min(100, item.percentage)) / 100)
            progress.set_size_request(110, -1)
            progress.set_valign(Gtk.Align.CENTER)
            progress.set_show_text(True)
            progress.set_text(f"{item.percentage:.0f}%")
            row.add_suffix(progress)
            if item.nzo_id:
                actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                paused = item.status.lower() == "paused"
                pause = Gtk.Button(
                    icon_name=(
                        "media-playback-start-symbolic"
                        if paused
                        else "media-playback-pause-symbolic"
                    ),
                    tooltip_text="Resume job" if paused else "Pause job",
                )
                pause.connect(
                    "clicked",
                    lambda button, job=item, target=not paused: self._set_sab_job_paused(
                        job, target, button
                    ),
                )
                remove = Gtk.Button(
                    icon_name="user-trash-symbolic", tooltip_text="Remove from queue"
                )
                remove.add_css_class("destructive-action")
                remove.connect(
                    "clicked", lambda _button, job=item: self._confirm_remove_queue_job(job)
                )
                actions.append(pause)
                actions.append(remove)
                row.add_suffix(actions)
            self.queue_list.append(row)
        self.queue_status.set_visible_child_name("items" if items else "empty")

    def _render_history(self, items: list[HistoryItem]) -> None:
        while child := self.history_list.get_first_child():
            self.history_list.remove(child)
        for item in items:
            details = [
                value
                for value in (item.status, item.size, item.category, item.completed_label)
                if value
            ]
            subtitle = "  •  ".join(details)
            if item.failure_description:
                subtitle = f"{subtitle}\n{item.failure_description}"
            row = Adw.ActionRow(title=item.name, subtitle=subtitle)
            row.set_title_lines(1)
            row.set_subtitle_lines(1)
            if item.failure_description:
                row.set_subtitle_lines(2)
                row.set_tooltip_text(item.failure_description)
            icon_name = (
                "emblem-ok-symbolic"
                if item.status.lower() == "completed"
                else "dialog-warning-symbolic"
            )
            icon = Gtk.Image.new_from_icon_name(icon_name)
            icon.set_tooltip_text(item.status)
            row.add_prefix(icon)
            if item.nzo_id:
                actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
                if item.status.lower() == "failed":
                    retry = Gtk.Button(
                        icon_name="view-refresh-symbolic", tooltip_text="Retry job"
                    )
                    retry.connect(
                        "clicked", lambda button, job=item: self._retry_history_job(job, button)
                    )
                    actions.append(retry)
                remove = Gtk.Button(
                    icon_name="edit-delete-symbolic", tooltip_text="Remove from history"
                )
                remove.connect(
                    "clicked", lambda _button, job=item: self._remove_history_job(job)
                )
                actions.append(remove)
                row.add_suffix(actions)
            self.history_list.append(row)
        self.history_status.set_visible_child_name("items" if items else "empty")

    def _set_sab_job_paused(
        self, item: QueueItem, paused: bool, button: Gtk.Button
    ) -> None:
        button.set_sensitive(False)
        action = "Paused" if paused else "Resumed"
        self._run_sab_action(
            lambda: SabnzbdClient(self.settings).set_job_paused(item.nzo_id, paused),
            f"{action} “{item.name}”",
            button,
        )

    def _confirm_remove_queue_job(self, item: QueueItem) -> None:
        dialog = Adw.MessageDialog.new(
            self,
            "Remove this job?",
            f"“{item.name}” will be removed from the SABnzbd queue. Already downloaded files will be kept.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_default_response("cancel")
        dialog.set_close_response("cancel")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)

        def responded(_dialog: Adw.MessageDialog, response: str) -> None:
            if response == "remove":
                self._run_sab_action(
                    lambda: SabnzbdClient(self.settings).delete_queue_job(item.nzo_id),
                    f"Removed “{item.name}” from the queue",
                )

        dialog.connect("response", responded)
        dialog.present()

    def _retry_history_job(self, item: HistoryItem, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        self._run_sab_action(
            lambda: SabnzbdClient(self.settings).retry_history_job(item.nzo_id),
            f"Retrying “{item.name}”",
            button,
        )

    def _remove_history_job(self, item: HistoryItem) -> None:
        self._run_sab_action(
            lambda: SabnzbdClient(self.settings).delete_history_job(item.nzo_id),
            f"Removed “{item.name}” from history",
        )

    def _run_sab_action(
        self,
        work: Callable[[], None],
        message: str,
        button: Gtk.Button | None = None,
    ) -> None:
        def done(_result: None) -> None:
            if button:
                button.set_sensitive(True)
            self._toast(message)
            self.refresh_queue()

        def failed(exc: Exception) -> None:
            if button:
                button.set_sensitive(True)
            self._request_failed(exc)

        _async(work, done, failed)

    def _toggle_sab_pause(self, button: Gtk.Button) -> None:
        target = not self._sab_paused
        button.set_sensitive(False)

        def done(_result: None) -> None:
            button.set_sensitive(True)
            self._sab_paused = target
            self._toast("SABnzbd paused" if target else "SABnzbd resumed")
            self.refresh_queue()

        def failed(exc: Exception) -> None:
            button.set_sensitive(True)
            self._request_failed(exc)

        _async(lambda: SabnzbdClient(self.settings).set_paused(target), done, failed)

    def open_settings(self, first_run: bool = False) -> None:
        dialog = SettingsWindow(self, self.settings, self._settings_saved)
        if first_run:
            dialog.set_title("Connect your services")
        dialog.present()

    def _settings_saved(self, settings: Settings) -> None:
        self.settings = settings
        self._toast("Settings saved")

    def _request_failed(self, exc: Exception) -> None:
        self.search_button.set_sensitive(True)
        self._toast(str(exc) if isinstance(exc, ApiError) else f"Something went wrong: {exc}")

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=4))


class SettingsWindow(Adw.PreferencesWindow):
    def __init__(
        self,
        parent: MainWindow,
        settings: Settings,
        on_saved: Callable[[Settings], None],
    ) -> None:
        super().__init__(title="Settings", transient_for=parent, modal=True)
        self.set_default_size(620, 620)
        self._on_saved = on_saved
        self._disabled_indexer_ids = list(settings.disabled_indexer_ids)
        page = Adw.PreferencesPage(title="Connections", icon_name="network-server-symbolic")

        prowlarr = Adw.PreferencesGroup(
            title="Prowlarr", description="Used to search all enabled Usenet indexers."
        )
        self.prowlarr_url = Adw.EntryRow(title="Server URL")
        self.prowlarr_url.set_text(settings.prowlarr_url)
        self.prowlarr_key = Adw.PasswordEntryRow(title="API key")
        self.prowlarr_key.set_text(settings.prowlarr_api_key)
        prowlarr.add(self.prowlarr_url)
        prowlarr.add(self.prowlarr_key)
        self.prowlarr_test = Adw.ActionRow(title="Connection status", subtitle="Not tested")
        prowlarr_button = Gtk.Button(label="Test")
        prowlarr_button.set_valign(Gtk.Align.CENTER)
        prowlarr_button.connect("clicked", lambda *_: self._test_prowlarr(prowlarr_button))
        self.prowlarr_test.add_suffix(prowlarr_button)
        prowlarr.add(self.prowlarr_test)
        page.add(prowlarr)

        sab = Adw.PreferencesGroup(
            title="SABnzbd", description="Receives NZBs and manages downloads."
        )
        self.sab_url = Adw.EntryRow(title="Server URL")
        self.sab_url.set_text(settings.sabnzbd_url)
        self.sab_key = Adw.PasswordEntryRow(title="API key")
        self.sab_key.set_text(settings.sabnzbd_api_key)
        self.sab_category = Adw.EntryRow(title="Category (optional)")
        self.sab_category.set_text(settings.sabnzbd_category)
        self.sab_priority = Adw.ComboRow(
            title="Priority",
            model=Gtk.StringList.new([label for label, _value in SAB_PRIORITIES]),
        )
        self.sab_priority.set_selected(
            next(
                (index for index, (_label, value) in enumerate(SAB_PRIORITIES) if value == settings.sabnzbd_priority),
                0,
            )
        )
        self.sab_post_processing = Adw.ComboRow(
            title="Post-processing",
            model=Gtk.StringList.new([label for label, _value in SAB_POST_PROCESSING]),
        )
        self.sab_post_processing.set_selected(
            next(
                (
                    index
                    for index, (_label, value) in enumerate(SAB_POST_PROCESSING)
                    if value == settings.sabnzbd_post_processing
                ),
                0,
            )
        )
        sab.add(self.sab_url)
        sab.add(self.sab_key)
        sab.add(self.sab_category)
        sab.add(self.sab_priority)
        sab.add(self.sab_post_processing)
        self.sab_test = Adw.ActionRow(title="Connection status", subtitle="Not tested")
        sab_button = Gtk.Button(label="Test")
        sab_button.set_valign(Gtk.Align.CENTER)
        sab_button.connect("clicked", lambda *_: self._test_sab(sab_button))
        self.sab_test.add_suffix(sab_button)
        sab.add(self.sab_test)
        page.add(sab)

        save_group = Adw.PreferencesGroup()
        save = Gtk.Button(label="Save connections")
        save.add_css_class("suggested-action")
        save.add_css_class("pill")
        save.set_halign(Gtk.Align.CENTER)
        save.connect("clicked", self._save)
        save_group.add(save)
        page.add(save_group)
        self.add(page)

    def _save(self, *_args: object) -> None:
        settings = self._current_settings()
        if not settings.prowlarr_url or not settings.sabnzbd_url:
            return
        settings.save()
        self._on_saved(settings)
        self.close()

    def _current_settings(self) -> Settings:
        return Settings(
            prowlarr_url=self.prowlarr_url.get_text().strip().rstrip("/"),
            prowlarr_api_key=self.prowlarr_key.get_text().strip(),
            sabnzbd_url=self.sab_url.get_text().strip().rstrip("/"),
            sabnzbd_api_key=self.sab_key.get_text().strip(),
            sabnzbd_category=self.sab_category.get_text().strip(),
            sabnzbd_priority=SAB_PRIORITIES[self.sab_priority.get_selected()][1],
            sabnzbd_post_processing=SAB_POST_PROCESSING[
                self.sab_post_processing.get_selected()
            ][1],
            disabled_indexer_ids=self._disabled_indexer_ids,
        )

    def _test_prowlarr(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        self.prowlarr_test.set_subtitle("Connecting…")

        def done(version: str) -> None:
            button.set_sensitive(True)
            self.prowlarr_test.set_subtitle(f"Connected • version {version}")

        def failed(exc: Exception) -> None:
            button.set_sensitive(True)
            self.prowlarr_test.set_subtitle(str(exc))

        _async(lambda: ProwlarrClient(self._current_settings()).test(), done, failed)

    def _test_sab(self, button: Gtk.Button) -> None:
        button.set_sensitive(False)
        self.sab_test.set_subtitle("Connecting…")

        def work() -> tuple[str, list[str]]:
            client = SabnzbdClient(self._current_settings())
            return client.test(), client.categories()

        def done(result: tuple[str, list[str]]) -> None:
            button.set_sensitive(True)
            version, categories = result
            selected = self.sab_category.get_text().strip()
            if selected and selected not in categories:
                self.sab_test.set_subtitle(
                    f"Connected • version {version} • category “{selected}” was not found"
                )
                self.sab_category.add_css_class("error")
            else:
                self.sab_test.set_subtitle(
                    f"Connected • version {version} • {len(categories)} categories"
                )
                self.sab_category.remove_css_class("error")

        def failed(exc: Exception) -> None:
            button.set_sensitive(True)
            self.sab_test.set_subtitle(str(exc))

        _async(work, done, failed)


CSS = """
.app-background { background: @window_bg_color; }
.hero-title { font-size: 26px; font-weight: 800; }
.search-button { padding-left: 22px; padding-right: 22px; }
.release-icon {
  background: alpha(@accent_bg_color, 0.14);
  color: @accent_color;
  border-radius: 12px;
}
.category-label { color: @accent_color; font-size: 0.88em; }
.sab-header-card {
  background: @card_bg_color;
  border: 1px solid alpha(@borders, 0.65);
  border-radius: 12px;
  padding: 14px 16px;
  box-shadow: 0 1px 3px alpha(black, 0.1);
}
.sab-brand-icon {
  background: alpha(@accent_bg_color, 0.16);
  color: @accent_color;
  border-radius: 10px;
  padding: 9px;
}
.sab-state { color: @accent_color; font-weight: 600; }
.sab-status-pill {
  background: alpha(@accent_bg_color, 0.14);
  color: @accent_color;
  border-radius: 999px;
  padding: 3px 9px;
  font-size: 0.82em;
  font-weight: 700;
}
.sab-status-paused { color: @warning_color; background: alpha(@warning_color, 0.14); }
.sab-status-failed { color: @error_color; background: alpha(@error_color, 0.14); }
.stat-card {
  background: @card_bg_color;
  border: 1px solid alpha(@borders, 0.6);
  border-radius: 12px;
  box-shadow: 0 1px 2px alpha(black, 0.08);
}
.stat-card .accent { color: @accent_color; }
row { transition: background 120ms ease; }
"""


def main() -> int:
    app = NzbCompassApplication()
    return app.run(sys.argv)
