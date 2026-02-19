"""GitHub watcher — monitors issues, comments, and PRs via PyGithub."""

from __future__ import annotations

from datetime import datetime, timezone

from github import Github, GithubException

from wingman.config import GitHubConfig
from wingman.database import Database
from wingman.watchers.base import BaseWatcher, WatcherItem


class GitHubWatcher(BaseWatcher):
    """Monitors GitHub repos for new issues, issue comments, and pull requests."""

    def __init__(self, config: GitHubConfig, db: Database) -> None:
        super().__init__(db)
        self.config = config
        self._github = Github(config.token)

    @property
    def name(self) -> str:
        return "GitHubWatcher"

    def check(self) -> list[WatcherItem]:
        new_items: list[WatcherItem] = []

        state = self.db.get_watcher_state(self.name)
        since = None
        if state and state.get("last_successful_at"):
            since = datetime.fromisoformat(state["last_successful_at"])

        for repo_name in self.config.repos:
            try:
                items = self._check_repo(repo_name, since)
                new_items.extend(items)
            except GithubException as e:
                self.logger.error("Failed checking repo %s: %s", repo_name, e)
            except Exception as e:
                self.logger.error(
                    "Unexpected error checking repo %s: %s", repo_name, e
                )

        remaining = self._github.rate_limiting[0]
        self.logger.info("GitHub API rate limit remaining: %d", remaining)

        return new_items

    def _check_repo(
        self, repo_name: str, since: datetime | None
    ) -> list[WatcherItem]:
        items: list[WatcherItem] = []
        full_name = f"{self.config.owner}/{repo_name}"
        repo = self._github.get_repo(full_name)

        # Check issues (includes PRs in GitHub API, filter separately)
        kwargs = {"state": "all", "sort": "updated", "direction": "desc"}
        if since:
            kwargs["since"] = since

        for issue in repo.get_issues(**kwargs):
            # Stop paging if we've gone past our since window
            if since and issue.updated_at < since:
                break

            if issue.pull_request:
                # This is a PR — handle separately
                source_id = f"{repo_name}#pr{issue.number}"
                item_type = "pr"
            else:
                source_id = f"{repo_name}#issue{issue.number}"
                item_type = "issue"

            if not self.is_seen("github", source_id, item_type):
                items.append(WatcherItem(
                    source="github",
                    source_id=source_id,
                    item_type=item_type,
                    repo_or_context=repo_name,
                    title=issue.title,
                    body=issue.body or "",
                    author=issue.user.login if issue.user else "unknown",
                    url=issue.html_url,
                    created_at=issue.created_at.isoformat(),
                ))

            # Check comments on this issue
            comment_kwargs = {}
            if since:
                comment_kwargs["since"] = since

            for comment in issue.get_comments(**comment_kwargs):
                comment_source_id = f"{repo_name}#comment{comment.id}"
                if not self.is_seen("github", comment_source_id, "comment"):
                    # Truncate long comments for the notification
                    body = comment.body or ""
                    items.append(WatcherItem(
                        source="github",
                        source_id=comment_source_id,
                        item_type="comment",
                        repo_or_context=repo_name,
                        title=f"Comment on #{issue.number}: {issue.title}",
                        body=body[:2000],
                        author=(
                            comment.user.login if comment.user else "unknown"
                        ),
                        url=comment.html_url,
                        created_at=comment.created_at.isoformat(),
                    ))

        return items
