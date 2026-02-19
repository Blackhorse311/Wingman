"""SPT-Forge watcher — monitors mod metadata via API and comments via scraping."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

from wingman.config import ForgeConfig, ForgeMod
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
        self._session.headers.update({"User-Agent": "Wingman/1.0"})
        self._authenticated = False

    @property
    def name(self) -> str:
        return "ForgeWatcher"

    def _ensure_authenticated(self) -> None:
        """Authenticate with the Forge API if not already."""
        if self._authenticated:
            return

        # Check for cached token first
        cached = self.db.get_forge_token()
        if cached:
            self._session.headers["Authorization"] = f"Bearer {cached}"
            # Verify it still works
            try:
                resp = self._session.get(
                    f"{FORGE_API_BASE}/auth/user",
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
                if resp.status_code == 200:
                    self._authenticated = True
                    return
            except requests.RequestException:
                pass

        # Login with credentials
        if not self.config.email or not self.config.password:
            self.logger.warning("Forge credentials not configured, skipping")
            return

        try:
            resp = self._session.post(
                f"{FORGE_API_BASE}/auth/login",
                json={
                    "email": self.config.email,
                    "password": self.config.password,
                    "token_name": "wingman",
                    "abilities": ["read"],
                },
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=15,
            )
            if not resp.ok:
                self.logger.error(
                    "Forge login failed (%d): %s", resp.status_code, resp.text[:500]
                )
                return
            data = resp.json()
            token = data.get("data", {}).get("token", "")
            if token:
                self._session.headers["Authorization"] = f"Bearer {token}"
                self.db.save_forge_token(token)
                self._authenticated = True
                self.logger.info("Authenticated with Forge API")
            else:
                self.logger.error("Forge login response missing token: %s", data)
        except requests.RequestException as e:
            self.logger.error("Forge authentication failed: %s", e)

    def check(self) -> list[WatcherItem]:
        new_items: list[WatcherItem] = []

        self._ensure_authenticated()

        for mod in self.config.mods:
            try:
                items = self._check_mod_metadata(mod)
                new_items.extend(items)
            except Exception as e:
                self.logger.error(
                    "Failed checking Forge mod metadata for %s: %s",
                    mod.name, e,
                )

            try:
                items = self._scrape_comments(mod)
                new_items.extend(items)
            except Exception as e:
                self.logger.warning(
                    "Failed scraping Forge comments for %s: %s",
                    mod.name, e,
                )

        return new_items

    def _mod_url(self, mod: ForgeMod) -> str:
        """Build the full mod page URL."""
        return f"{FORGE_BASE_URL}/mod/{mod.id}/{mod.slug}"

    @retry(max_attempts=2, base_delay=10.0, exceptions=(requests.RequestException,))
    def _check_mod_metadata(self, mod: ForgeMod) -> list[WatcherItem]:
        """Check for new mod versions via the Forge API."""
        items: list[WatcherItem] = []

        if not self._authenticated:
            self.logger.debug("Not authenticated, skipping API check for %s", mod.name)
            return items

        resp = self._session.get(
            f"{FORGE_API_BASE}/mod/{mod.id}/versions",
            headers={"Accept": "application/json"},
            timeout=15,
        )

        # Re-auth on 401
        if resp.status_code == 401:
            self._authenticated = False
            self._ensure_authenticated()
            if not self._authenticated:
                return items
            resp = self._session.get(
                f"{FORGE_API_BASE}/mod/{mod.id}/versions",
                headers={"Accept": "application/json"},
                timeout=15,
            )

        resp.raise_for_status()
        data = resp.json()

        versions = data.get("data", data) if isinstance(data, dict) else data
        if isinstance(versions, dict):
            versions = versions.get("data", [])
        if not isinstance(versions, list):
            versions = []

        for version in versions:
            version_num = version.get("version", "unknown")
            source_id = f"{mod.name}#version_{version_num}"

            if not self.is_seen("forge", source_id, "mod_update"):
                spt_versions = ", ".join(
                    v.get("version", "?")
                    for v in version.get("spt_versions", [])
                )
                items.append(WatcherItem(
                    source="forge",
                    source_id=source_id,
                    item_type="mod_update",
                    repo_or_context=mod.name,
                    title=f"{mod.name} v{version_num}",
                    body=f"New version {version_num} for SPT {spt_versions}",
                    author="You",
                    url=self._mod_url(mod),
                    created_at=version.get("created_at", ""),
                ))

        return items

    @retry(max_attempts=2, base_delay=10.0, exceptions=(requests.RequestException,))
    def _scrape_comments(self, mod: ForgeMod) -> list[WatcherItem]:
        """Scrape the mod page for comments.

        Forge uses Livewire for dynamic content. We attempt to parse
        whatever is available in the initial HTML render. If comments
        are JS-only, we degrade gracefully and log a warning.
        """
        items: list[WatcherItem] = []

        page_url = self._mod_url(mod)
        resp = self._session.get(
            page_url,
            headers={"Accept": "text/html"},
            timeout=30,
        )
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "html.parser")
        comments = self._extract_comments_from_html(soup)

        if not comments:
            self.logger.debug(
                "No comments found in HTML for %s (may require JS rendering)",
                mod.name,
            )
            return items

        for comment in comments:
            author = comment.get("author", "unknown")
            body = comment.get("body", "")
            timestamp = comment.get("timestamp", "")

            content_hash = hashlib.md5(
                f"{author}:{body[:100]}:{timestamp}".encode()
            ).hexdigest()[:12]
            source_id = f"{mod.name}#comment_{content_hash}"

            if not self.is_seen("forge", source_id, "mod_comment"):
                items.append(WatcherItem(
                    source="forge",
                    source_id=source_id,
                    item_type="mod_comment",
                    repo_or_context=mod.name,
                    title=f"Comment on {mod.name}",
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

        comment_containers = soup.select(
            "[class*='comment'], [id*='comment'], "
            "[data-comment], [wire\\:id]"
        )

        for container in comment_containers:
            author_el = container.select_one(
                "[class*='author'], [class*='user'], "
                "[class*='name'], a[href*='/user/']"
            )
            author = author_el.get_text(strip=True) if author_el else "unknown"

            body_el = container.select_one(
                "[class*='body'], [class*='content'], "
                "[class*='text'], [class*='message'], p"
            )
            body = body_el.get_text(strip=True) if body_el else ""

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

            if body:
                comments.append({
                    "author": author,
                    "body": body,
                    "timestamp": timestamp,
                })

        return comments
