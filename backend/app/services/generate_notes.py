from __future__ import annotations

import json
import uuid
from typing import Any

import google.generativeai as genai
from google.generativeai import GenerationConfig
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.schemas import Mode, Topic, DeriveTopics, clamp_snippet


def _topic_bullets_for_mode(mode: Mode) -> tuple[int, int]:
    settings = get_settings()
    if mode == Mode.short:
        return settings.TOPICS_SHORT, settings.BULLETS_PER_TOPIC_SHORT
    if mode == Mode.detailed:
        return settings.TOPICS_DETAILED, settings.BULLETS_PER_TOPIC_DETAILED
    return settings.TOPICS_BALANCED, settings.BULLETS_PER_TOPIC_BALANCED


def _pick_snippet_instruction() -> str:
    return (
        "For each bullet, include citations.snippet as a DIRECT QUOTE taken verbatim from the SOURCE_TEXT. "
        "The snippet must appear exactly in SOURCE_TEXT (after whitespace normalization). "
        "Use very short snippets (max 200 characters)."
    )


def _strip_markdown_code_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    lines = text.split("\n")
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _extract_balanced_object(text: str) -> str | None:
    """Find first top-level {...} JSON object by brace counting."""
    text = _strip_markdown_code_fence(text)
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == "\"":
                in_str = False
            continue
        if ch == "\"":
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _gemini_response_text(resp: Any) -> str:
    """`.text` can be empty when blocked or when candidates lack a text part."""
    try:
        t = getattr(resp, "text", None)
        if t and str(t).strip():
            return str(t).strip()
    except ValueError:
        pass

    parts: list[str] = []
    for cand in getattr(resp, "candidates", None) or []:
        content = getattr(cand, "content", None)
        if content is None:
            continue
        for part in getattr(content, "parts", None) or []:
            txt = getattr(part, "text", None)
            if txt:
                parts.append(txt)
    return "\n".join(parts).strip()


def _parse_topics_payload(raw: str) -> dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        raise ValueError("Gemini returned an empty response (no text to parse as JSON).")

    blob = _extract_balanced_object(raw) or raw
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        preview = raw[:400].replace("\n", " ")
        raise ValueError(
            f"Gemini did not return valid JSON ({e}). Preview: {preview!r}"
        ) from e

    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object with a 'topics' key.")
    topics = data.get("topics")
    if topics is None:
        raise ValueError("JSON object must include a 'topics' array.")
    if not isinstance(topics, list):
        raise ValueError("'topics' must be a JSON array.")
    return data


@retry(wait=wait_exponential(min=1, max=10), stop=stop_after_attempt(2))
def generate_topics_with_gemini(*, source_text: str, mode: Mode) -> DeriveTopics:
    settings = get_settings()
    if not settings.GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not set.")

    topics_k, bullets_per_topic = _topic_bullets_for_mode(mode)

    # Very long sources can produce empty/truncated model output; cap what we send to Gemini.
    max_llm_chars = 100_000
    source_for_prompt = source_text[:max_llm_chars]
    if len(source_text) > max_llm_chars:
        source_for_prompt += "\n\n[... document truncated for note generation ...]\n"

    # Keep prompt grounded: we only allow snippet citations that must match SOURCE_TEXT.
    prompt = (
        "You are LexiNote, a tool that converts long articles into topic-wise study notes.\n"
        "Return ONLY valid JSON. Do not include markdown.\n\n"
        f"MODE: {mode.value}\n"
        f"MAX_TOPICS: {topics_k}\n"
        f"BULLETS_PER_TOPIC: {bullets_per_topic}\n"
        "CITATIONS_ENABLED: true\n\n"
        "SOURCE_TEXT:\n"
        f"{source_for_prompt}\n\n"
        "TASK:\n"
        "- Derive topics that best summarize the main ideas.\n"
        "- For each topic, produce bullet notes.\n"
        "- Keep bullets concise: each bullet should be a single takeaway.\n\n"
        f"{_pick_snippet_instruction()}\n\n"
        "OUTPUT JSON SCHEMA (match keys exactly):\n"
        "{\n"
        '  "topics": [\n'
        "    {\n"
        '      "id": string,\n'
        '      "title": string,\n'
        '      "bullets": [\n'
        "        {\n"
        '          "id": string,\n'
        '          "text": string,\n'
        '          "citations": [ { "snippet": string, "chunkIndex": number|null } ]\n'
        "        }\n"
        "      ]\n"
        "    }\n"
        "  ],\n"
        '  "coverageNote": string,\n'
        '  "coverageScore": number\n'
        "}\n"
    )

    genai.configure(api_key=settings.GEMINI_API_KEY)

    json_cfg = GenerationConfig(
        response_mime_type="application/json",
        temperature=0.35,
    )
    text_cfg = GenerationConfig(temperature=0.35)

    # Reliability: try configured model first, then fallbacks.
    candidates: list[str] = [settings.GEMINI_MODEL, *settings.GEMINI_MODEL_FALLBACKS]
    seen: set[str] = set()
    model_attempt_errors: list[str] = []

    data: dict[str, Any] | None = None

    for cand in candidates:
        data = None
        cand = cand.strip()
        if not cand or cand in seen:
            continue
        seen.add(cand)

        model_name = cand
        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        model = genai.GenerativeModel(model_name)

        for label, cfg in (("json_mode", json_cfg), ("text_mode", text_cfg)):
            try:
                resp = model.generate_content(prompt, generation_config=cfg)
                raw = _gemini_response_text(resp)
                if not raw:
                    model_attempt_errors.append(f"{model_name} ({label}): empty response from Gemini")
                    continue
                data = _parse_topics_payload(raw)
                break
            except Exception as e:
                err_msg = str(e)
                model_attempt_errors.append(f"{model_name} ({label}): {err_msg}")
                msg = err_msg.lower()
                if label == "json_mode" and (
                    "response mime type" in msg
                    or "mime type" in msg
                    or "unsupported" in msg
                    or "not supported" in msg
                ):
                    continue
                if "not found" in msg or "does not exist" in msg:
                    data = None
                    break
                if label == "text_mode":
                    data = None
                    break
                continue

        if data is not None:
            break

    if data is None:
        raise RuntimeError(
            "Gemini could not produce valid topic JSON. "
            + " | ".join(model_attempt_errors)[-2000:]
        )

    # Normalize IDs so the editor can render stable keys.
    topics = []
    for t in data.get("topics", []):
        tid = str(t.get("id") or f"topic-{uuid.uuid4().hex[:8]}")
        bullets = []
        for b in t.get("bullets", []):
            bid = str(b.get("id") or f"b-{uuid.uuid4().hex[:8]}")
            citations_in = b.get("citations") or []
            citations = []
            for c in citations_in:
                if c is None:
                    continue
                raw_snippet = str(c.get("snippet") or "").strip()
                if raw_snippet:
                    citations.append(
                        {
                            "snippet": clamp_snippet(raw_snippet),
                            "chunkIndex": c.get("chunkIndex", None),
                        }
                    )
            bullets.append({"id": bid, "text": str(b.get("text") or "").strip(), "citations": citations})

        topics.append({"id": tid, "title": str(t.get("title") or "").strip(), "bullets": bullets})

    return DeriveTopics(
        topics=[Topic.model_validate(t) for t in topics],
        coverageNote=str(data.get("coverageNote") or "").strip() or None,
        coverageScore=float(data.get("coverageScore")) if data.get("coverageScore") is not None else None,
    )

