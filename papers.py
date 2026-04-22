import re
import fitz

ACADEMIC_DOMAINS = [
    "arxiv.org", "doi.org", "semanticscholar.org", "aclweb.org",
    "openreview.net", "papers.nips.cc", "proceedings.mlr.press",
    "ieee.org", "springer.com", "nature.com", "science.org", "pnas.org",
]


def extract_paper_links(pdf_bytes: bytes) -> list[str]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    urls = set()
    text_parts = []
    for page in doc:
        for link in page.get_links():
            uri = link.get("uri", "")
            if uri:
                urls.add(uri)
        text_parts.append(page.get_text())
    doc.close()

    text = "\n".join(text_parts)

    for m in re.finditer(r'https?://[^\s,;}\]"\'<>)+]+', text):
        urls.add(m.group(0).rstrip(".,)"))

    for m in re.finditer(r'(10\.\d{4,9}/[^\s,;}\]"\'<>]+)', text):
        urls.add(f"https://doi.org/{m.group(1).rstrip('.')}")

    for m in re.finditer(r'arXiv[:\s]+(\d{4}\.\d{4,5})', text):
        urls.add(f"https://arxiv.org/abs/{m.group(1)}")

    paper_urls = set()
    for url in urls:
        normalized = _normalize(url)
        if normalized:
            paper_urls.add(normalized)

    return list(paper_urls)


def _normalize(url: str) -> str | None:
    if "arxiv.org" in url:
        m = re.search(r'(\d{4}\.\d{4,5})', url)
        return f"https://arxiv.org/abs/{m.group(1)}" if m else None

    if "doi.org/" in url:
        m = re.search(r'(10\.\d{4,9}/[^\s,;}\]"\'<>]+)', url)
        return f"https://doi.org/{m.group(1).rstrip('.')}" if m else None

    if any(d in url for d in ACADEMIC_DOMAINS):
        return url

    return None
