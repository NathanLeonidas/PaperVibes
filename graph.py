import asyncio
import hashlib
import html as html_mod
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import httpx

from papers import extract_paper_links
from search import download_pdf, to_pdf_url, web_search

executor = ThreadPoolExecutor(max_workers=8)

TITLE_SUFFIXES = [
    " - arXiv.org", " | OpenReview", " - ACL Anthology",
    " | Papers With Code", " | Semantic Scholar",
]


def _make_id(s: str) -> str:
    return hashlib.md5(s.lower().strip().encode()).hexdigest()[:12]


def _resolve_title(url: str) -> str | None:
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as client:
            r = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            r.raise_for_status()
            m = re.search(r'<title[^>]*>(.*?)</title>', r.text, re.DOTALL | re.IGNORECASE)
            if m:
                title = re.sub(r'\s+', ' ', m.group(1)).strip()
                for suffix in TITLE_SUFFIXES:
                    title = title.removesuffix(suffix)
                title = re.sub(r'^\[\d{4}\.\d{4,5}]\s*', '', title)
                title = html_mod.unescape(title)
                if len(title) > 5:
                    return title
    except Exception:
        pass
    return None


def _fetch_ref_links(url: str) -> tuple[str, list[str]]:
    pdf_url = to_pdf_url(url)
    if not pdf_url:
        return url, []
    data = download_pdf(pdf_url)
    if not data:
        return url, []
    return url, extract_paper_links(data)


def _search_pdf_only(query: str):
    return web_search(query, max_results=10, pdf_only=True)


async def search_papers(query: str) -> list[dict]:
    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(executor, _search_pdf_only, query)
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "pdf_url": r.get("pdf_url", ""),
            "snippet": r.get("body", ""),
        }
        for r in results
    ]


async def build_graph(query: str, pdf_url: str | None = None, max_refs: int = 20) -> dict:
    loop = asyncio.get_event_loop()

    if not pdf_url:
        results = await loop.run_in_executor(executor, _search_pdf_only, query)
        for r in results:
            if r.get("pdf_url"):
                pdf_url = r["pdf_url"]
                break
        if not pdf_url:
            return {"error": "Could not find a PDF for this query."}

    seed_pdf = await loop.run_in_executor(executor, download_pdf, pdf_url)
    if not seed_pdf:
        return {"error": "Could not download the PDF."}

    seed_id = _make_id(pdf_url)
    seed_links = extract_paper_links(seed_pdf)
    if not seed_links:
        return {"error": "No paper links found in the PDF."}

    seed_links = [l for l in seed_links if _make_id(l) != seed_id][:max_refs]

    # url -> outgoing paper links
    links_map: dict[str, set[str]] = {pdf_url: set(seed_links)}

    # Depth 1: fetch PDFs for seed's direct references
    d1_fetchable = [url for url in seed_links if to_pdf_url(url)]
    d1_tasks = [loop.run_in_executor(executor, _fetch_ref_links, url) for url in d1_fetchable]
    d1_results = await asyncio.gather(*d1_tasks)

    for url, links in d1_results:
        if links:
            links_map[url] = set(links)

    # Depth 2: surface papers cited by 2+ depth-1 papers
    known_urls = {pdf_url} | set(seed_links)
    d2_counts: Counter = Counter()
    for _, links in d1_results:
        for link in links:
            if link not in known_urls and _make_id(link) != seed_id:
                d2_counts[link] += 1

    d2_candidates = [url for url, count in d2_counts.most_common() if count >= 2][:max_refs]

    d2_fetchable = [url for url in d2_candidates if to_pdf_url(url)]
    if d2_fetchable:
        d2_tasks = [loop.run_in_executor(executor, _fetch_ref_links, url) for url in d2_fetchable]
        for url, links in await asyncio.gather(*d2_tasks):
            if links:
                links_map[url] = set(links)

    # Resolve titles
    all_paper_urls = list(set(seed_links) | set(d2_candidates))
    title_tasks = [loop.run_in_executor(executor, _resolve_title, url) for url in all_paper_urls]
    titles = await asyncio.gather(*title_tasks)
    url_to_title = {url: t for url, t in zip(all_paper_urls, titles) if t}

    # Build nodes
    seed_link_set = set(seed_links)
    nodes = [{
        "id": seed_id, "title": query, "url": pdf_url,
        "is_seed": True, "has_pdf": True, "depth": 0, "cite_count": 0,
    }]

    url_to_id: dict[str, str] = {}
    seen_ids: set[str] = {seed_id}
    for url in all_paper_urls:
        title = url_to_title.get(url)
        if not title:
            continue
        nid = _make_id(url)
        if nid in seen_ids:
            continue
        seen_ids.add(nid)
        url_to_id[url] = nid
        is_d1 = url in seed_link_set
        nodes.append({
            "id": nid, "title": title, "url": url,
            "is_seed": False, "has_pdf": to_pdf_url(url) is not None,
            "depth": 1 if is_d1 else 2,
            "cite_count": d2_counts.get(url, 1 if is_d1 else 0),
        })

    # Map node IDs to their link sets
    id_links = {seed_id: links_map.get(pdf_url, set())}
    for url, nid in url_to_id.items():
        id_links[nid] = links_map.get(url, set())

    # Build edges (Jaccard on shared outgoing links)
    edges = []
    node_ids = [n["id"] for n in nodes]
    for i in range(len(node_ids)):
        for j in range(i + 1, len(node_ids)):
            a, b = node_ids[i], node_ids[j]
            la, lb = id_links.get(a, set()), id_links.get(b, set())

            if la and lb:
                sim = len(la & lb) / len(la | lb)
            elif a == seed_id or b == seed_id:
                sim = 0.03
            else:
                sim = 0

            if sim > 0.005:
                edges.append({"source": a, "target": b, "weight": sim})

    # PageRank
    pr = _pagerank(node_ids, edges)
    for n in nodes:
        n["pagerank"] = pr.get(n["id"], 0)

    return {"nodes": nodes, "edges": edges, "seed_id": seed_id, "pdf_url": pdf_url}


def _pagerank(node_ids: list[str], edges: list[dict],
              damping: float = 0.85, iterations: int = 40) -> dict[str, float]:
    n = len(node_ids)
    if n == 0:
        return {}

    scores = {nid: 1.0 / n for nid in node_ids}
    adj: dict[str, list[tuple[str, float]]] = {nid: [] for nid in node_ids}
    out_weight: dict[str, float] = {nid: 0.0 for nid in node_ids}

    for e in edges:
        s, t, w = e["source"], e["target"], e["weight"]
        adj[t].append((s, w))
        adj[s].append((t, w))
        out_weight[s] += w
        out_weight[t] += w

    for _ in range(iterations):
        new_scores = {}
        for nid in node_ids:
            rank_sum = sum(
                scores[nb] * w / out_weight[nb]
                for nb, w in adj[nid]
                if out_weight[nb] > 0
            )
            new_scores[nid] = (1 - damping) / n + damping * rank_sum
        scores = new_scores

    return scores
