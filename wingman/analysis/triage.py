"""AI triage module — classifies items using Claude."""

from __future__ import annotations

import json
import logging

import anthropic

from wingman.config import TriageConfig
from wingman.notifications.formatter import TriageResult
from wingman.watchers.base import WatcherItem

logger = logging.getLogger(__name__)

TRIAGE_PROMPT = """You are a triage assistant for a software mod developer (Blackhorse311).
Analyze the following {item_type} from {source} and classify it.

Title: {title}
Body: {body}
Author: {author}
Context: {repo_or_context}

Respond in JSON format only:
{{
    "classification": "<one of: bug_report, feature_request, question, praise, complaint, spam>",
    "severity": "<one of: critical, high, medium, low>",
    "summary": "<one sentence summary>",
    "reasoning": "<brief explanation>"
}}

Classification guidelines:
- bug_report: Something is broken or not working as expected
- feature_request: Request for new functionality or enhancement
- question: User asking for help or clarification
- praise: Positive feedback, thanks, or compliments
- complaint: Negative feedback that isn't a specific bug report
- spam: Irrelevant, promotional, or bot-generated content

Severity guidelines:
- critical: Crash, data loss, security issue, or completely blocks usage
- high: Major functionality broken, affects many users
- medium: Minor bug, reasonable feature request, or question needing attention
- low: Cosmetic issue, praise, minor suggestion, or spam"""


class TriageAnalyzer:
    """Analyzes incoming items using Claude to classify and prioritize."""

    def __init__(self, config: TriageConfig) -> None:
        self.client = anthropic.Anthropic(api_key=config.api_key)
        self.model = config.model

    def analyze(self, item: WatcherItem) -> TriageResult:
        """Classify an item using Claude. Returns a TriageResult."""
        if not self.client.api_key:
            logger.warning("Anthropic API key not configured, skipping triage")
            return _fallback_result()

        prompt = TRIAGE_PROMPT.format(
            item_type=item.item_type,
            source=item.source,
            title=item.title,
            body=item.body[:1500],  # Limit to control token usage
            author=item.author,
            repo_or_context=item.repo_or_context,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}],
            )

            text = response.content[0].text.strip()
            # Handle response wrapped in markdown code blocks
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                if text.endswith("```"):
                    text = text[: -len("```")]
                text = text.strip()

            data = json.loads(text)

            return TriageResult(
                classification=data.get("classification", "unclassified"),
                severity=data.get("severity", "unknown"),
                summary=data.get("summary", ""),
                reasoning=data.get("reasoning", ""),
            )

        except json.JSONDecodeError as e:
            logger.warning("Failed to parse triage response as JSON: %s", e)
            return _fallback_result()
        except anthropic.APIError as e:
            logger.error("Anthropic API error during triage: %s", e)
            return _fallback_result()


def _fallback_result() -> TriageResult:
    """Return a default result when triage is unavailable."""
    return TriageResult(
        classification="unclassified",
        severity="unknown",
        summary="AI triage unavailable",
        reasoning="",
    )
