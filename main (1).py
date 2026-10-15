# main.py | Python 3.11+ | FastAPI + Playwright + OpenAI
# Run: uvicorn main:app --reload
# Frontend: static/index.html served at /

import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from playwright.async_api import async_playwright

from scraper import create_context, facebook_login, scrape_post, scrape_page_posts
from analyzer import analyze_content, generate_page_report
from reporter import report_post, bulk_report

load_dotenv()

# Global Playwright state — reused across requests
_playwright = None
_browser = None
_context = None
SESSION_PATH = "fb_session.json"


async def get_context():
    global _playwright, _browser, _context
    if _context is None:
        _playwright = await async_playwright().start()
        _browser, _context = await create_context(_playwright, SESSION_PATH)
    return _context


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: init playwright
    await get_context()
    yield
    # Shutdown: close browser
    if _browser:
        await _browser.close()
    if _playwright:
        await _playwright.stop()


app = FastAPI(title="Facebook Report AI", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ─── Request Models ───────────────────────────────────────────────

class LoginRequest(BaseModel):
    email: str
    password: str

class PostAnalyzeRequest(BaseModel):
    url: str

class PageAnalyzeRequest(BaseModel):
    page_url: str
    limit: int = 10

class ReportRequest(BaseModel):
    url: str
    reason: str  # hate_speech | spam | misinformation | violence | harassment

class BulkReportRequest(BaseModel):
    page_url: str
    limit: int = 10
    auto_report: bool = False


# ─── Endpoints ────────────────────────────────────────────────────

@app.post("/api/login")
async def login(req: LoginRequest):
    """Login to Facebook and save session."""
    ctx = await get_context()
    page = await ctx.new_page()
    try:
        await facebook_login(page, req.email, req.password, SESSION_PATH)
        return {"success": True, "message": "Logged in successfully"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        await page.close()


@app.post("/api/analyze/post")
async def analyze_post(req: PostAnalyzeRequest):
    """Scrape and analyze a single FB post."""
    ctx = await get_context()
    post_data = await scrape_post(req.url, ctx)
    if "error" in post_data:
        raise HTTPException(status_code=422, detail=post_data["error"])
    analysis = await analyze_content(post_data)
    return analysis


@app.post("/api/analyze/page")
async def analyze_page(req: PageAnalyzeRequest):
    """Scrape and analyze all posts from a FB page."""
    ctx = await get_context()
    posts = await scrape_page_posts(req.page_url, ctx, req.limit)
    if not posts:
        raise HTTPException(status_code=422, detail="No posts found")
    analyses = await asyncio.gather(*[analyze_content(p) for p in posts])
    report = await generate_page_report(list(analyses), req.page_url)
    return report


@app.post("/api/report/single")
async def report_single(req: ReportRequest):
    """Report a single post."""
    ctx = await get_context()
    result = await report_post(req.url, req.reason, ctx)
    return result


@app.post("/api/report/bulk")
async def report_bulk(req: BulkReportRequest):
    """Analyze page and optionally auto-report flagged posts."""
    ctx = await get_context()
    posts = await scrape_page_posts(req.page_url, ctx, req.limit)
    if not posts:
        raise HTTPException(status_code=422, detail="No posts scraped")

    analyses = list(await asyncio.gather(*[analyze_content(p) for p in posts]))
    report = await generate_page_report(analyses, req.page_url)

    report_results = []
    if req.auto_report:
        report_results = await bulk_report(analyses, ctx)

    return {
        "analysis_report": report,
        "report_actions": report_results
    }


@app.get("/")
async def root():
    return FileResponse("static/index.html")
