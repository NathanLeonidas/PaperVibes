import re
from urllib.parse import quote_plus, unquote

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
    all_results = []
    suffixes = ["filetype:pdf", "pdf"] if pdf_only else [""]

    for suffix in suffixes:
        q = f"{query} {suffix}".strip()
        url = f"https://html.duckduckgo.com/html/?q={quote_plus(q)}"
        try:
            r = httpx.get(url, headers={"User-Agent": USER_AGENT}, timeout=15, follow_redirects=True)
            r.raise_for_status()
        except Exception:
            continue

        blocks = re.findall(
            r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            r.text, re.DOTALL,
        )
        seen = {r["href"] for r in all_results}
        for href, title_html, snippet_html in blocks:
            href_match = re.search(r'uddg=([^&]+)', href)
            actual_url = unquote(href_match.group(1)) if href_match else href

            pdf_url = to_pdf_url(actual_url)
            if pdf_only and not pdf_url:
                continue

            deduped_url = pdf_url or actual_url
            if deduped_url in seen:
                continue
            seen.add(deduped_url)

            all_results.append({
                "title": re.sub(r'<[^>]+>', '', title_html).strip(),
                "href": actual_url,
                "pdf_url": pdf_url,
                "body": re.sub(r'<[^>]+>', '', snippet_html).strip(),
            })
            if len(all_results) >= max_results:
                break

        if len(all_results) >= max_results:
            break

    return all_results


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
