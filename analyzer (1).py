# analyzer.py | Python 3.11+ | OpenAI SDK v1.x
# GPT-4o: gpt-4o model, ~$0.005/1K tokens input, ~$0.015/1K output
# All analysis done via structured system prompts

import json
import os
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


async def analyze_content(post: dict) -> dict:
    """
    Full content analysis of a single post.
    Returns: {
        sentiment, toxicity_score, spam_score,
        hate_speech, reportable, report_reason,
        summary, categories
    }
    toxicity_score/spam_score: 0.0-1.0 float
    """
    text = post.get("text", "")
    comments = "\n".join(post.get("raw_comments", [])[:10])

    prompt = f"""Analyze this Facebook post and its comments for content moderation.

POST TEXT:
{text}

TOP COMMENTS:
{comments}

Respond in this exact JSON format:
{{
  "sentiment": "positive|negative|neutral",
  "toxicity_score": 0.0,
  "spam_score": 0.0,
  "hate_speech": true,
  "misinformation_risk": true,
  "reportable": true,
  "report_reason": "specific reason or null",
  "report_category": "hate_speech|spam|misinformation|violence|harassment|none",
  "summary": "2 sentence Bengali or English summary",
  "severity": "low|medium|high|critical"
}}

Be accurate. toxicity_score 0.8+ = should be reported."""

    try:
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a content moderation AI. Always respond with valid JSON only."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        result["post_url"] = post.get("url", "")
        result["post_text"] = text[:200]
        return result
    except Exception as e:
        return {"error": str(e), "post_url": post.get("url", ""), "reportable": False}


async def generate_page_report(posts_analysis: list[dict], page_url: str) -> dict:
    """
    Generates aggregate performance + moderation report for a page.
    posts_analysis: list of analyze_content() results
    Returns full report dict
    """
    total = len(posts_analysis)
    reportable = [p for p in posts_analysis if p.get("reportable")]
    avg_toxicity = sum(p.get("toxicity_score", 0) for p in posts_analysis) / max(total, 1)
    avg_spam = sum(p.get("spam_score", 0) for p in posts_analysis) / max(total, 1)

    categories = {}
    for p in reportable:
        cat = p.get("report_category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1

    severities = {}
    for p in posts_analysis:
        sev = p.get("severity", "low")
        severities[sev] = severities.get(sev, 0) + 1

    summary_prompt = f"""Based on analysis of {total} Facebook posts from {page_url}:
- {len(reportable)} posts are reportable
- Average toxicity: {avg_toxicity:.2f}
- Average spam score: {avg_spam:.2f}
- Report categories: {categories}
- Severity breakdown: {severities}

Write a concise moderation report summary in 3-4 sentences. Identify main issues and risk level."""

    try:
        resp = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a social media moderation analyst."},
                {"role": "user", "content": summary_prompt}
            ],
            temperature=0.3
        )
        ai_summary = resp.choices[0].message.content
    except Exception:
        ai_summary = "Summary generation failed."

    return {
        "page_url": page_url,
        "total_posts_analyzed": total,
        "reportable_count": len(reportable),
        "reportable_percentage": round(len(reportable) / max(total, 1) * 100, 1),
        "avg_toxicity_score": round(avg_toxicity, 3),
        "avg_spam_score": round(avg_spam, 3),
        "category_breakdown": categories,
        "severity_breakdown": severities,
        "reportable_posts": reportable,
        "ai_summary": ai_summary,
        "risk_level": "critical" if avg_toxicity > 0.7 else "high" if avg_toxicity > 0.4 else "medium" if avg_toxicity > 0.2 else "low"
    }
