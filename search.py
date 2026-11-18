import re
import xml.etree.ElementTree as ET

import httpx

USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"


def to_pdf_url(url: str) -> str | None:
    if url.lower().endswith(".pdf"):
        return url
    if "arxiv.org/abs/" in url:
        arxiv_id = url.rstrip("/").split("/")[-1]
        return f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    if "arxiv.org/pdf/" in url:
        return url if url.endswith(".pdf") else url + ".pdf"
    return None


def web_search(query: str, max_results: int = 10, pdf_only: bool = False) -> list[dict]:
    """Search arXiv for papers. Returns a list of dicts with keys
    ``title``, ``href`` (abs url), ``pdf_url`` and ``body`` (abstract)."""
    # Phrase-match the whole query across all arXiv fields.
    search_query = f'all:"{query}"'
    params = {
        "search_query": search_query,
        "start": 0,
        "max_results": max_results,
    }
    try:
        r = httpx.get(
            "https://export.arxiv.org/api/query",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
        )
        r.raise_for_status()
    except Exception:
        return []

    root = ET.fromstring(r.text)
    atom = "{http://www.w3.org/2005/Atom}"
    entries = root.findall(f"{atom}entry")

    results: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        raw_id = (e.findtext(f"{atom}id") or "").strip()
        # id is like http://arxiv.org/abs/2401.12345v7 -> strip trailing version
        abs_url = re.sub(r"v\d+$", "", raw_id)
        title = re.sub(r"\s+", " ", (e.findtext(f"{atom}title") or "")).strip()
        summary = re.sub(r"\s+", " ", (e.findtext(f"{atom}summary") or "")).strip()

        pdf_url = to_pdf_url(abs_url)
        if pdf_only and not pdf_url:
            continue
        if abs_url in seen:
            continue
        seen.add(abs_url)

        results.append({
            "title": title,
            "href": abs_url,
            "pdf_url": pdf_url,
            "body": summary,
        })

    return results


def download_pdf(url: str, timeout: int = 30) -> bytes | None:
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": USER_AGENT})
            r.raise_for_status()
            if "pdf" in r.headers.get("content-type", "") or r.content[:5] == b"%PDF-":
                return r.content
    except Exception:
        pass
    return None
