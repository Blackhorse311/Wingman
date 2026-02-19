"""Main scheduler — orchestrates watchers, triage, and notifications."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from wingman.analysis.triage import TriageAnalyzer
from wingman.config import WingmanConfig
from wingman.database import Database
from wingman.notifications.email_notifier import EmailNotifier
from wingman.notifications.formatter import (
    FormattedNotification,
    TriageResult,
    format_notification,
    format_watcher_failure,
)
from wingman.notifications.sms_notifier import SmsNotifier
from wingman.watchers.base import BaseWatcher, WatcherItem
from wingman.watchers.forge_watcher import ForgeWatcher
from wingman.watchers.github_watcher import GitHubWatcher
from wingman.watchers.reddit_watcher import RedditWatcher

logger = logging.getLogger(__name__)


class WingmanScheduler:
    """Orchestrates all watchers on independent schedules."""

    def __init__(self, config: WingmanConfig) -> None:
        self.config = config
        self.db = Database(config.database_path)
        self.triage = TriageAnalyzer(config.triage)
        self.notifiers = [
            EmailNotifier(config.notifications),
            SmsNotifier(config.notifications),
        ]
        self.scheduler = BlockingScheduler()
        self._watchers: list[tuple[BaseWatcher, int]] = []
        self._init_watchers()

    def _init_watchers(self) -> None:
        """Initialize all configured watchers."""
        self._watchers.append((
            GitHubWatcher(self.config.github, self.db),
            self.config.github.check_interval_minutes,
        ))

        self._watchers.append((
            ForgeWatcher(self.config.forge, self.db),
            self.config.forge.check_interval_minutes,
        ))

        if self.config.reddit.enabled:
            self._watchers.append((
                RedditWatcher(self.config.reddit, self.db),
                self.config.reddit.check_interval_minutes,
            ))
            logger.info("Reddit watcher enabled for r/%s", self.config.reddit.subreddit)
        else:
            logger.info("Reddit watcher disabled (set reddit.enabled = true to activate)")

    def _run_watcher(self, watcher: BaseWatcher) -> None:
        """Execute a single watcher check cycle with full error isolation."""
        logger.info("Running %s...", watcher.name)

        try:
            new_items = watcher.check()

            if new_items:
                logger.info("%s found %d new item(s)", watcher.name, len(new_items))

            first_run = self.db.is_first_run(watcher.name)

            for item in new_items:
                self._process_item(watcher, item, first_run)

            self.db.update_watcher_state(watcher.name, successful=True)

        except Exception as e:
            logger.error("%s failed: %s", watcher.name, e, exc_info=True)
            self.db.update_watcher_state(watcher.name, successful=False)

            failures = self.db.get_consecutive_failures(watcher.name)
            if failures >= 5 and failures % 5 == 0:
                self._notify_watcher_failure(watcher, failures, str(e))

    def _process_item(
        self,
        watcher: BaseWatcher,
        item: WatcherItem,
        first_run: bool,
    ) -> None:
        """Triage, store, and notify for a single new item."""
        # AI triage (with graceful fallback)
        try:
            result = self.triage.analyze(item)
        except Exception as e:
            logger.warning("Triage failed for %s: %s", item.source_id, e)
            result = TriageResult(
                classification="unclassified",
                severity="unknown",
                summary="AI triage unavailable",
            )

        # Store in database
        watcher.mark_seen(item)
        self.db.update_triage(
            source=item.source,
            source_id=item.source_id,
            item_type=item.item_type,
            classification=result.classification,
            severity=result.severity,
            summary=result.summary,
        )

        # First run: seed only, don't notify (unless configured otherwise)
        if first_run and not self.config.first_run_notify:
            logger.debug(
                "First run — seeding %s without notification", item.source_id
            )
            return

        # Format and send notifications
        notification = format_notification(
            source=item.source,
            source_id=item.source_id,
            item_type=item.item_type,
            repo_or_context=item.repo_or_context,
            title=item.title,
            body=item.body,
            author=item.author,
            url=item.url,
            triage=result,
        )
        self._send_notification(notification)

    def _notify_watcher_failure(
        self, watcher: BaseWatcher, failures: int, error: str
    ) -> None:
        """Send a meta-notification about a persistently failing watcher."""
        state = self.db.get_watcher_state(watcher.name)
        last_success = (
            state.get("last_successful_at", "Never") if state else "Never"
        )
        notification = format_watcher_failure(
            watcher_name=watcher.name,
            failures=failures,
            error=error,
            last_success=last_success,
        )
        self._send_notification(notification)

    def _send_notification(self, notification: FormattedNotification) -> None:
        """Send a notification through all configured notifiers."""
        for notifier in self.notifiers:
            try:
                notifier.send(notification)
            except Exception as e:
                logger.error(
                    "%s failed to send: %s",
                    notifier.__class__.__name__,
                    e,
                    exc_info=True,
                )

    def start(self) -> None:
        """Register all watchers and start the blocking scheduler."""
        for watcher, interval in self._watchers:
            self.scheduler.add_job(
                self._run_watcher,
                trigger=IntervalTrigger(minutes=interval),
                args=[watcher],
                id=watcher.name,
                name=f"Check {watcher.name}",
                next_run_time=datetime.now(timezone.utc),
                misfire_grace_time=300,
                coalesce=True,
                max_instances=1,
            )
            logger.info(
                "Scheduled %s every %d minutes", watcher.name, interval
            )

        watcher_count = len(self._watchers)
        logger.info(
            "Wingman started — monitoring with %d watcher(s). Press Ctrl+C to stop.",
            watcher_count,
        )
        self.scheduler.start()

    def shutdown(self) -> None:
        """Gracefully shut down the scheduler and database."""
        logger.info("Shutting down Wingman...")
        self.scheduler.shutdown(wait=False)
        self.db.close()
