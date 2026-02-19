"""Reddit watcher — monitors a subreddit for new posts and comments via PRAW."""

from __future__ import annotations

from datetime import datetime, timezone

import praw
import prawcore

from wingman.config import RedditConfig
from wingman.database import Database
from wingman.watchers.base import BaseWatcher, WatcherItem


class RedditWatcher(BaseWatcher):
    """Monitors a subreddit for new posts and comments."""

    def __init__(self, config: RedditConfig, db: Database) -> None:
        super().__init__(db)
        self.config = config
        self._reddit = praw.Reddit(
            client_id=config.client_id,
            client_secret=config.client_secret,
            username=config.username,
            password=config.password,
            user_agent=config.user_agent,
        )

    @property
    def name(self) -> str:
        return "RedditWatcher"

    def check(self) -> list[WatcherItem]:
        if not self.config.enabled:
            self.logger.debug("Reddit watcher is disabled, skipping")
            return []

        new_items: list[WatcherItem] = []
        subreddit_name = self.config.subreddit

        try:
            subreddit = self._reddit.subreddit(subreddit_name)
            # Access a property to verify the subreddit exists
            _ = subreddit.id
        except prawcore.exceptions.NotFound:
            self.logger.warning(
                "Subreddit r/%s not found. Skipping.", subreddit_name
            )
            return []
        except prawcore.exceptions.Forbidden:
            self.logger.warning(
                "Access denied to r/%s. Skipping.", subreddit_name
            )
            return []
        except prawcore.exceptions.Redirect:
            self.logger.warning(
                "Subreddit r/%s redirected (may not exist). Skipping.",
                subreddit_name,
            )
            return []

        # Check new posts
        try:
            items = self._check_submissions(subreddit)
            new_items.extend(items)
        except Exception as e:
            self.logger.error(
                "Failed checking submissions for r/%s: %s",
                subreddit_name, e,
            )

        # Check new comments
        try:
            items = self._check_comments(subreddit)
            new_items.extend(items)
        except Exception as e:
            self.logger.error(
                "Failed checking comments for r/%s: %s",
                subreddit_name, e,
            )

        return new_items

    def _check_submissions(
        self, subreddit: praw.models.Subreddit
    ) -> list[WatcherItem]:
        items: list[WatcherItem] = []

        for submission in subreddit.new(limit=25):
            source_id = submission.fullname  # t3_xxxxx
            if not self.is_seen("reddit", source_id, "post"):
                created = datetime.fromtimestamp(
                    submission.created_utc, tz=timezone.utc
                )
                items.append(WatcherItem(
                    source="reddit",
                    source_id=source_id,
                    item_type="post",
                    repo_or_context=self.config.subreddit,
                    title=submission.title,
                    body=(submission.selftext or "")[:2000],
                    author=str(submission.author) if submission.author else "[deleted]",
                    url=f"https://reddit.com{submission.permalink}",
                    created_at=created.isoformat(),
                ))

        return items

    def _check_comments(
        self, subreddit: praw.models.Subreddit
    ) -> list[WatcherItem]:
        items: list[WatcherItem] = []

        for comment in subreddit.comments(limit=50):
            source_id = comment.fullname  # t1_xxxxx
            if not self.is_seen("reddit", source_id, "comment"):
                created = datetime.fromtimestamp(
                    comment.created_utc, tz=timezone.utc
                )
                # Get the parent submission title for context
                try:
                    submission_title = comment.submission.title
                except Exception:
                    submission_title = "(unknown post)"

                items.append(WatcherItem(
                    source="reddit",
                    source_id=source_id,
                    item_type="comment",
                    repo_or_context=self.config.subreddit,
                    title=f"Comment on: {submission_title}",
                    body=(comment.body or "")[:2000],
                    author=str(comment.author) if comment.author else "[deleted]",
                    url=f"https://reddit.com{comment.permalink}",
                    created_at=created.isoformat(),
                ))

        return items
