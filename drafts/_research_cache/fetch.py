#!/usr/bin/env python
"""Fetch research sources -> text. PDF via pymupdf, HTML via bs4."""
import hashlib
import os
import re
import sys

import httpx
import fitz
from bs4 import BeautifulSoup

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_research_cache")
os.makedirs(OUT, exist_ok=True)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/pdf,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def slug(url: str) -> str:
    base = re.sub(r"[^A-Za-z0-9]+", "-", url)[-90:].strip("-")
    return base or hashlib.md5(url.encode()).hexdigest()[:12]


def html_to_text(raw: bytes) -> str:
    soup = BeautifulSoup(raw, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "noscript", "svg"]):
        tag.decompose()
    text = soup.get_text("\n")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def pdf_to_text(raw: bytes) -> str:
    doc = fitz.open(stream=raw, filetype="pdf")
    parts = []
    for i, page in enumerate(doc):
        parts.append(f"\n=== PAGE {i+1} ===\n" + page.get_text())
    return "".join(parts)


def fetch(url: str, max_chars: int = 400000) -> tuple[str, str]:
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=60) as c:
            r = c.get(url)
        if r.status_code >= 400:
            return "", f"HTTP {r.status_code}"
        raw = r.content
        ctype = r.headers.get("content-type", "")
        if "pdf" in ctype or url.lower().endswith(".pdf") or raw[:4] == b"%PDF":
            text = pdf_to_text(raw)
        else:
            text = html_to_text(raw)
        if len(text) < 300:
            return text, f"THIN ({len(text)} chars) ctype={ctype}"
        return text[:max_chars], f"OK {len(text)} chars ctype={ctype.split(';')[0]}"
    except Exception as e:  # noqa: BLE001
        return "", f"ERR {type(e).__name__}: {e}"


if __name__ == "__main__":
    urls = [u for u in sys.argv[1:] if u]
    for u in urls:
        path = os.path.join(OUT, slug(u) + ".txt")
        if os.path.exists(path) and os.path.getsize(path) > 500:
            print(f"[cached] {os.path.getsize(path):>7}  {u}\n         -> {path}")
            continue
        text, status = fetch(u)
        if text:
            with open(path, "w") as f:
                f.write(f"SOURCE: {u}\n\n{text}")
        print(f"[{status}]  {u}\n         -> {path}")
