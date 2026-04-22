from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, Response

from graph import build_graph, search_papers
from search import download_pdf, to_pdf_url

app = FastAPI()


@app.get("/", response_class=HTMLResponse)
async def index():
    return Path("templates/index.html").read_text()


@app.get("/api/search")
async def api_search(q: str = Query(..., min_length=1)):
    return {"results": await search_papers(q)}


@app.get("/api/graph")
async def api_graph(
    q: str = Query(...),
    pdf_url: str = Query(None),
    max_refs: int = Query(15, ge=3, le=30),
):
    return await build_graph(q, pdf_url=pdf_url, max_refs=max_refs)


@app.get("/api/pdf")
async def api_pdf(url: str = Query(...)):
    data = download_pdf(to_pdf_url(url) or url)
    if not data:
        return Response(status_code=404, content="PDF not found")
    return Response(content=data, media_type="application/pdf")
