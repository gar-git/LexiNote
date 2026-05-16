from __future__ import annotations

from typing import Iterable

from app.core.config import get_settings
from app.schemas import DeriveTopics, Topic, Bullet, Citation, Mode


def _normalize_for_match(s: str) -> str:
    # Must match normalize_text in fetch_extract.
    return " ".join(s.replace("\u00a0", " ").split())


def _snippet_is_from_source(*, snippet: str, source_text: str) -> bool:
    # Exact substring check on normalized strings.
    sn = _normalize_for_match(snippet)
    st = _normalize_for_match(source_text)
    if not sn:
        return False
    return sn in st


def filter_invalid_topics(*, topics: DeriveTopics, source_text: str, mode: Mode) -> DeriveTopics:
    settings = get_settings()
    if not topics.topics:
        return topics

    topics_k, bullets_per_topic = (
        (settings.TOPICS_SHORT, settings.BULLETS_PER_TOPIC_SHORT)
        if mode == Mode.short
        else (settings.TOPICS_DETAILED, settings.BULLETS_PER_TOPIC_DETAILED)
        if mode == Mode.detailed
        else (settings.TOPICS_BALANCED, settings.BULLETS_PER_TOPIC_BALANCED)
    )

    filtered_topics: list[Topic] = []
    for t in topics.topics[:topics_k]:
        bullets: list[Bullet] = []
        for b in t.bullets[:bullets_per_topic]:
            b_citations = []
            for c in b.citations:
                if c.snippet and _snippet_is_from_source(snippet=c.snippet, source_text=source_text):
                    b_citations.append(c)
            # Reliability rule:
            # - If citations are enabled, keep only bullets that have at least 1 verified citation.
            if settings.CITATIONS_ENABLED:
                if not b_citations:
                    continue
                b_citations = b_citations[:1]
            else:
                b_citations = b.citations[:1]

            bullets.append(Bullet(id=b.id, text=b.text, citations=b_citations))

        if bullets:
            filtered_topics.append(Topic(id=t.id, title=t.title, bullets=bullets))

    coverage_note = topics.coverageNote
    if settings.CITATIONS_ENABLED:
        coverage_note = (coverage_note or "").strip()
        if filtered_topics and len(filtered_topics) < len(topics.topics):
            coverage_note = (coverage_note + " (Some bullets were removed due to unverified snippets.)").strip()

    return DeriveTopics(
        topics=filtered_topics,
        coverageNote=coverage_note or None,
        coverageScore=topics.coverageScore,
    )

