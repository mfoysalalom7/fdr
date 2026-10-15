# reporter.py | Python 3.11+ | Playwright async
# Handles auto-reporting flow on Facebook
# Gotcha: FB report UI changes frequently — selectors may need updating

import asyncio
from playwright.async_api import BrowserContext

REPORT_REASONS = {
    "hate_speech": "It's hate speech",
    "spam": "It's spam",
    "misinformation": "False information",
    "violence": "Violence",
    "harassment": "Bullying or harassment",
}


async def report_post(url: str, reason: str, context: BrowserContext) -> dict:
    """
    Attempts to auto-report a Facebook post.
    url: post URL
    reason: key from REPORT_REASONS dict
    Returns: {success, steps_completed, error}
    Gotcha: FB actively detects automation — rate limit to 1 report/30s minimum
    """
    page = await context.new_page()
    result = {"url": url, "reason": reason, "success": False, "steps_completed": []}

    try:
        await page.goto(url, wait_until="domcontentloaded", timeout=20000)
        await page.wait_for_timeout(2000)

        # Click "..." (more options) button on post
        more_btn = await page.query_selector("[aria-label='More']")
        if not more_btn:
            more_btn = await page.query_selector("div[aria-haspopup='menu'][role='button']")
        if not more_btn:
            result["error"] = "Could not find options button"
            return result

        await more_btn.click()
        result["steps_completed"].append("opened_menu")
        await page.wait_for_timeout(1000)

        # Find "Report post" option
        report_option = await page.get_by_text("Report post", exact=False).first.element_handle()
        if not report_option:
            result["error"] = "Report option not found in menu"
            return result

        await report_option.click()
        result["steps_completed"].append("clicked_report")
        await page.wait_for_timeout(1500)

        # Select report reason
        reason_text = REPORT_REASONS.get(reason, "It's spam")
        reason_btn = await page.get_by_text(reason_text, exact=False).first.element_handle()
        if reason_btn:
            await reason_btn.click()
            result["steps_completed"].append("selected_reason")
            await page.wait_for_timeout(1000)

        # Click submit/next
        submit_btn = await page.query_selector("[aria-label='Submit'], [aria-label='Next'], button:has-text('Submit'), button:has-text('Done')")
        if submit_btn:
            await submit_btn.click()
            result["steps_completed"].append("submitted")
            await page.wait_for_timeout(2000)
            result["success"] = True
        else:
            result["error"] = "Submit button not found"

    except Exception as e:
        result["error"] = str(e)
    finally:
        await page.close()

    return result


async def bulk_report(posts: list[dict], context: BrowserContext, delay_sec: int = 35) -> list[dict]:
    """
    Reports multiple posts sequentially with delay.
    delay_sec: minimum 30s between reports to avoid FB detection
    posts: list of {url, report_category} dicts from analyzer
    """
    results = []
    for post in posts:
        if post.get("reportable") and post.get("report_category") != "none":
            r = await report_post(post["post_url"], post["report_category"], context)
            results.append(r)
            await asyncio.sleep(delay_sec)  # rate limit
    return results
