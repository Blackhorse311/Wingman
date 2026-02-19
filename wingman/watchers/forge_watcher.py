"""SPT-Forge watcher — monitors mod metadata via API and comments via scraping."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from wingman.config import ForgeConfig
from wingman.database import Database
from wingman.utils.retry import retry
from wingman.watchers.base import BaseWatcher, WatcherItem

FORGE_API_BASE = "https://forge.sp-tarkov.com/api/v0"
FORGE_BASE_URL = "https://forge.sp-tarkov.com"

logger = logging.getLogger(__name__)


class ForgeWatcher(BaseWatcher):
    """Monitors SPT-Forge for mod metadata changes and new comments."""

    def __init__(self, config: ForgeConfig, db: Database) -> None:
        super().__init__(db)
        self.config = config
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Wingman/1.0",
            "Accept": "application/json",
        })

    @property
    def name(self) -> str:
        return "ForgeWatcher"

    def check(self) -> list[WatcherItem]:
        new_items: list[WatcherItem] = []

        for mod_name, mod_id in self.config.mods.items():
            try:
                # Part 1: API-based metadata check
                items = self._check_mod_metadata(mod_name, mod_id)
                new_items.extend(items)
            except Exception as e:
                self.logger.error(
                    "Failed checking Forge mod metadata for %s: %s",
                    mod_name, e,
                )

            try:
                # Part 2: Scrape comments
                items = self._scrape_comments(mod_name, mod_id)
                new_items.extend(items)
            except Exception as e:
                self.logger.warning(
                    "Failed scraping Forge comments for %s: %s",
                    mod_name, e,
                )

        return new_items

    @retry(max_attempts=2, base_delay=10.0, exceptions=(requests.RequestException,))
    def _check_mod_metadata(
        self, mod_name: str, mod_id: int
    ) -> list[WatcherItem]:
        """Check for new mod versions via the Forge API."""
        items: list[WatcherItem] = []

        resp = self._session.get(f"{FORGE_API_BASE}/mod/{mod_id}/versions")
        resp.raise_for_status()
        data = resp.json()

        versions = data.get("data", [])
        for version in versions:
            version_num = version.get("version", "unknown")
            source_id = f"{mod_name}#version_{version_num}"

            if not self.is_seen("forge", source_id, "mod_update"):
                spt_versions = ", ".join(
                    v.get("version", "?")
                    for v in version.get("spt_versions", [])
                )
                items.append(WatcherItem(
                    source="forge",
                    source_id=source_id,
                    item_type="mod_update",
                    repo_or_context=mod_name,
                    title=f"{mod_name} v{version_num}",
                    body=f"New version {version_num} for SPT {spt_versions}",
                    author="You",
                    url=f"{FORGE_BASE_URL}/mod/{mod_id}",
                    created_at=version.get("created_at", ""),
                ))

        return items

    @retry(max_attempts=2, base_delay=10.0, exceptions=(requests.RequestException,))
    def _scrape_comments(
        self, mod_name: str, mod_id: int
    ) -> list[WatcherItem]:
        """Scrape the mod page for comments.

        Forge uses Livewire for dynamic content. We attempt to parse
        whatever is available in the initial HTML render. If comments
        are JS-only, we degrade gracefully and log a warning.
        """
        items: list[WatcherItem] = []

        # Fetch the mod page HTML
        page_url = f"{FORGE_BASE_URL}/mod/{mod_id}"
        resp = self._session.get(
            page_url,
            headers={"Accept": "text/html"},
            timeout=30,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")

        # Look for comment elements — Forge uses various structures
        # Try common patterns for comment sections
        comments = self._extract_comments_from_html(soup)

        if not comments:
            self.logger.debug(
                "No comments found in HTML for %s (may require JS rendering)",
                mod_name,
            )
            return items

        for comment in comments:
            author = comment.get("author", "unknown")
            body = comment.get("body", "")
            timestamp = comment.get("timestamp", "")

            # Create a stable ID from comment content
            content_hash = hashlib.md5(
                f"{author}:{body[:100]}:{timestamp}".encode()
            ).hexdigest()[:12]
            source_id = f"{mod_name}#comment_{content_hash}"

            if not self.is_seen("forge", source_id, "mod_comment"):
                items.append(WatcherItem(
                    source="forge",
                    source_id=source_id,
                    item_type="mod_comment",
                    repo_or_context=mod_name,
                    title=f"Comment on {mod_name}",
                    body=body[:2000],
                    author=author,
                    url=page_url,
                    created_at=timestamp,
                ))

        return items

    def _extract_comments_from_html(
        self, soup: BeautifulSoup
    ) -> list[dict[str, str]]:
        """Extract comments from parsed HTML.

        Tries multiple selector strategies to handle different page structures.
        Returns a list of dicts with 'author', 'body', and 'timestamp' keys.
        """
        comments: list[dict[str, str]] = []

        # Strategy 1: Look for elements with comment-related classes/IDs
        # Forge/Livewire typically renders comments in a structured way
        comment_containers = soup.select(
            "[class*='comment'], [id*='comment'], "
            "[data-comment], [wire\\:id]"
        )

        for container in comment_containers:
            # Try to extract author
            author_el = container.select_one(
                "[class*='author'], [class*='user'], "
                "[class*='name'], a[href*='/user/']"
            )
            author = author_el.get_text(strip=True) if author_el else "unknown"

            # Try to extract body
            body_el = container.select_one(
                "[class*='body'], [class*='content'], "
                "[class*='text'], [class*='message'], p"
            )
            body = body_el.get_text(strip=True) if body_el else ""

            # Try to extract timestamp
            time_el = container.select_one(
                "time, [class*='date'], [class*='time'], "
                "[datetime], [class*='ago']"
            )
            timestamp = ""
            if time_el:
                timestamp = (
                    time_el.get("datetime", "")
                    or time_el.get_text(strip=True)
                )

            if body:  # Only include if we got actual content
                comments.append({
                    "author": author,
                    "body": body,
                    "timestamp": timestamp,
                })

        return comments
