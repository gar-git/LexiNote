from __future__ import annotations

import ipaddress
import socket
from typing import Iterable
from urllib.parse import urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup

from app.core.config import get_settings


def _iter_host_ips(host: str) -> Iterable[str]:
    for res in socket.getaddrinfo(host, None):
        ip = res[4][0]
        yield ip


def _is_ip_private(ip_str: str) -> bool:
    ip = ipaddress.ip_address(ip_str)
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved


def normalize_article_url(url: str) -> str:
    """Strip whitespace; add https:// if user pasted example.com with no scheme."""
    u = (url or "").strip()
    if not u:
        return u
    parsed = urlparse(u)
    if not parsed.scheme:
        u = "https://" + u
    elif parsed.scheme not in {"http", "https"}:
        return u
    return u


def validate_url_safety(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed.")
    if not parsed.netloc:
        raise ValueError("Invalid URL.")

    host = parsed.hostname
    assert host is not None
    for ip_str in _iter_host_ips(host):
        if _is_ip_private(ip_str):
            raise ValueError("Blocked private/internal URL.")


def _looks_like_html(raw: str) -> bool:
    head = raw.lstrip()[:12000].lower()
    return (
        "<html" in head
        or "<!doctype html" in head
        or "<article" in head
        or "<body" in head
        or "<main" in head
    )


def _acceptable_content_type(content_type: str, raw: str) -> bool:
    ct = (content_type or "").lower()
    if not ct.strip():
        return _looks_like_html(raw)
    if "text/" in ct or "html" in ct or "xml" in ct or "json" in ct:
        # json pages are rare for articles; still allow if we later sniff HTML inside
        if "json" in ct and not _looks_like_html(raw):
            return False
        return True
    return _looks_like_html(raw)


def _trafilatura_extract(raw: str, page_url: str | None) -> str | None:
    text = trafilatura.extract(
        raw,
        url=page_url,
        output_format="txt",
        include_comments=False,
        include_tables=True,
    )
    if text and text.strip():
        return text.strip()
    text = trafilatura.extract(
        raw,
        url=page_url,
        output_format="txt",
        include_comments=False,
        favor_recall=True,
        include_tables=True,
    )
    if text and text.strip():
        return text.strip()
    return None


def _fallback_bs4_extract(raw: str) -> str | None:
    try:
        soup = BeautifulSoup(raw, "lxml")
    except Exception:
        soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "template"]):
        tag.decompose()
    root = soup.find("article") or soup.find("main") or soup.find("body")
    if not root:
        return None
    text = root.get_text("\n", strip=True)
    lines = [ln for ln in (ln.strip() for ln in text.splitlines()) if ln]
    joined = "\n".join(lines)
    return joined.strip() or None


def fetch_url_text(url: str) -> str:
    """Fetch URL and extract main text. Sync API for workers / background tasks."""
    settings = get_settings()
    url = normalize_article_url(url)
    if not url:
        raise ValueError("URL is empty.")
    validate_url_safety(url)

    limits = httpx.Limits(max_connections=5, max_keepalive_connections=5)
    # One default for all phases — avoids "set all four parameters" across httpx versions.
    timeout = httpx.Timeout(90.0)

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36 LexiNote/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    with httpx.Client(limits=limits, timeout=timeout, headers=headers, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()

        final_url = str(resp.url)

        if int(resp.headers.get("content-length", "0") or "0") > settings.MAX_URL_DOWNLOAD_BYTES:
            raise ValueError("URL content too large.")

        raw = resp.text
        if len(raw) > settings.MAX_URL_DOWNLOAD_BYTES:
            raise ValueError("URL content too large.")

        content_type = resp.headers.get("content-type", "")
        if not _acceptable_content_type(content_type, raw):
            raise ValueError(
                "URL did not return HTML or plain text we could read. "
                "Try pasting the article text instead, or use a direct article link."
            )

    extracted = _trafilatura_extract(raw, final_url)
    if not extracted:
        extracted = _fallback_bs4_extract(raw)

    if not extracted or not extracted.strip():
        raise ValueError(
            "Could not extract readable article text from this page. "
            "The site may require a login, block automated access, or render content only in JavaScript. "
            "Try pasting the text instead."
        )

    return extracted.strip()


def normalize_text(text: str) -> str:
    """Normalize whitespace for pasted text (matches snippet matching in validator)."""
    return " ".join(text.replace("\u00a0", " ").split())
