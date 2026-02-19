"""Base watcher interface and shared data model."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from wingman.database import Database


@dataclass
class WatcherItem:
    """A single item discovered by a watcher."""

    source: str           # 'github', 'forge', 'reddit'
    source_id: str        # unique identifier within the source
    item_type: str        # 'issue', 'comment', 'pr', 'post', 'mod_comment', 'mod_update'
    repo_or_context: str  # repo name, mod slug, or subreddit
    title: str
    body: str
    author: str
    url: str
    created_at: str       # ISO timestamp from the source


class BaseWatcher(ABC):
    """Abstract base class for platform watchers."""

    def __init__(self, db: Database) -> None:
        self.db = db
        self.logger = logging.getLogger(self.__class__.__name__)

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this watcher (used in watcher_state table)."""
        ...

    @abstractmethod
    def check(self) -> list[WatcherItem]:
        """Fetch and return new items not previously seen.

        Implementations should:
        1. Query their platform for recent items
        2. Filter out items already in the database via is_seen()
        3. Return only genuinely new items
        """
        ...

    def is_seen(self, source: str, source_id: str, item_type: str) -> bool:
        """Check if an item has already been recorded."""
        return self.db.is_seen(source, source_id, item_type)

    def mark_seen(self, item: WatcherItem) -> None:
        """Record an item in the database."""
        self.db.mark_seen(
            source=item.source,
            source_id=item.source_id,
            item_type=item.item_type,
            repo_or_context=item.repo_or_context,
            title=item.title,
            body=item.body,
            author=item.author,
            url=item.url,
            created_at=item.created_at,
        )
