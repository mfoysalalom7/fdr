# scraper.py | Python 3.11+ | Playwright async
# Playwright: headless Chromium, Facebook login session maintained via storage_state
# OpenAI: used in analyzer.py, not here

import asyncio
import json
from playwright.async_api import async_playwright, Page, BrowserContext

async def create_context(playwright, storage_path: str = "fb_session.json"):
    """
    Creates Playwright browser context.
    Reuses saved session if exists, prevents repeated login.
    storage_path: JSON file storing cookies/localStorage after login
    """
    browser = await playwright.chromium.launch(headless=False)
    try:
        context = await browser.new_context(storage_state=storage_path)
        print("[scraper] Session loaded.")
    except FileNotFoundError:
        context = await browser.new_context()
        print("[scraper] No session found. Fresh context.")
    return browser, context


async def facebook_login(page: Page, email: str, password: str, storage_path: str):
    """
    Logs into Facebook and saves session.
    email/password: FB credentials
    storage_path: where to save session JSON
    """
    await page.goto("https://www.facebook.com/")
    await page.wait_for_selector("#email", timeout=10000)
    await page.fill("#email", email)
    await page.fill("#pass", password)
    await page.click("[name='login']")
    await page.wait_for_url("https://www.facebook.com/", timeout=15000)
    await page.context.storage_state(path=storage_path)
    print("[scraper] Login successful. Session saved.")


async def scrape_post(url: str, context: BrowserContext) -> dict:
    """
    Scrapes a single Facebook post.
    Returns: {url, text, reactions, comments, shares, timestamp}
    Gotcha: Dynamic content — wait_for_selector needed, not just load
    """
    page = await context.new_page()
    result = {
        "url": url,
        "text": "",
        "reactions": 0,
        "comments": 0,
        "shares": 0,
        "timestamp": "",
        "raw_comments": []
    }

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)  # JS render wait

        # Extract post text
        try:
            text_el = await page.query_selector('[data-ad-comet-preview="message"]')
            if not text_el:
                text_el = await page.query_selector('[data-ad-preview="message"]')
            if text_el:
                result["text"] = await text_el.inner_text()
        except Exception:
            pass

        # Extract timestamp
        try:
            time_el = await page.query_selector("abbr[data-utime]")
            if not time_el:
                time_el = await page.query_selector("a[role='link'] > span > span")
            if time_el:
                result["timestamp"] = await time_el.get_attribute("data-utime") or await time_el.inner_text()
        except Exception:
            pass

        # Extract reaction count
        try:
            reaction_el = await page.query_selector("[aria-label*='reaction']")
            if reaction_el:
                txt = await reaction_el.inner_text()
                result["reactions"] = _parse_count(txt)
        except Exception:
            pass

        # Extract comments (visible)
        try:
            comment_els = await page.query_selector_all('[aria-label="Comment"]')
            raw = []
            for c in comment_els[:20]:  # cap at 20
                try:
                    raw.append(await c.inner_text())
                except Exception:
                    pass
            result["raw_comments"] = raw
            result["comments"] = len(raw)
        except Exception:
            pass

    except Exception as e:
        result["error"] = str(e)
    finally:
        await page.close()

    return result


async def scrape_page_posts(page_url: str, context: BrowserContext, limit: int = 10) -> list[dict]:
    """
    Scrapes multiple posts from a Facebook page/profile.
    page_url: FB page URL
    limit: max posts to collect (~10 default)
    Gotcha: Infinite scroll — iteratively scrolls and collects post links
    """
    page = await context.new_page()
    post_urls = []

    try:
        await page.goto(page_url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(3000)

        # Collect post links by scrolling
        for _ in range(limit // 3 + 1):
            links = await page.eval_on_selector_all(
                "a[href*='/posts/'], a[href*='/videos/'], a[href*='/photos/']",
                "els => els.map(e => e.href)"
            )
            for l in links:
                if l not in post_urls:
                    post_urls.append(l)
            if len(post_urls) >= limit:
                break
            await page.evaluate("window.scrollBy(0, 1500)")
            await page.wait_for_timeout(2000)

    except Exception as e:
        print(f"[scraper] Page scrape error: {e}")
    finally:
        await page.close()

    # Scrape each collected post
    tasks = [scrape_post(u, context) for u in post_urls[:limit]]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return [r for r in results if isinstance(r, dict)]


def _parse_count(text: str) -> int:
    """Parses '1.2K', '3M', '450' style counts to int."""
    text = text.strip().replace(",", "")
    try:
        if "K" in text:
            return int(float(text.replace("K", "")) * 1000)
        elif "M" in text:
            return int(float(text.replace("M", "")) * 1_000_000)
        return int(text.split()[0])
    except Exception:
        return 0
