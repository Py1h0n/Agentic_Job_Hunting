"""
BDJobs Vision-Based Scraper
============================
Uses Playwright + Vision LLM (gemma-3-27b-it) for fast, reliable extraction.
Replaces the browser-use agent in turbo mode.
"""

import asyncio
import os
import re
import json
import base64
import time
import shutil
from pathlib import Path
from datetime import datetime
from typing import Any
import sys

import dotenv
from openai import AsyncOpenAI
from playwright.async_api import async_playwright

# Add parent to path for imports
sys.path.append(str(Path(__file__).parent.parent))
from database import save_jobs_to_db
import job_queue

dotenv.load_dotenv()

# Config
NEBIUS_API_KEY = os.getenv("NEBIUS_API_KEY", "")
NEBIUS_VISION_MODEL = os.getenv(
    "NEBIUS_RESUME_MODEL", "google/gemma-3-27b-it-fast"
)  # Changed to FAST model
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "results"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MAX_BROWSER_CONCURRENCY = int(
    os.getenv("MAX_BROWSER_CONCURRENCY", "5")
)  # Faster - 5 parallel browsers
MAX_AI_CONCURRENCY = int(os.getenv("MAX_AI_CONCURRENCY", "5"))  # Faster - 5 parallel AI
MAX_JOBS = 30

BLOCKED_RESOURCES = [
    "google-analytics.com",
    "googletagmanager.com",
    "facebook.net",
    "doubleclick.net",
    "criteo.net",
    "smartadserver.com",
]

SCREENSHOT_DIR = Path("bdjobs_screenshots")

stats = {"total_found": 0, "captured": 0, "ai_processed": 0, "errors": 0}

SYSTEM_PROMPT = """You are a job data extraction expert. Analyze this bdjobs job listing screenshot and extract structured data.

Extract these EXACT fields (return valid JSON only, no markdown):
{
  "title": "job title from the page",
  "company": "company name (the REAL employer, not platform)",
  "location": "city/area location",
  "job_type": "full-time/part-time/contract/etc",
  "deadline": "application deadline date",
  "salary": "salary range if visible (or empty string)",
  "experience": "experience requirements (or empty string)",
  "skills": "comma-separated skills (or empty string)",
  "requirements": "key requirements text (or empty string)",
  "responsibilities": "key responsibilities text (or empty string)",
  "benefits": "benefits text (or empty string)"
}

If a field is not visible or not applicable, use empty string "". 
Return ONLY valid JSON, no explanation."""


async def encode_image(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


async def process_with_ai(
    job: dict,
    client: AsyncOpenAI,
    ai_sem: asyncio.Semaphore,
    s_id: int = 0,
    u_id: int = 0,
) -> dict:
    """Process a single job with AI vision and emit SSE event after each."""
    async with ai_sem:
        job_name = job.get("title", "unknown")[:40]
        print(f"  🧠 [AI] Analyzing: {job_name}...")

        try:
            b64 = await encode_image(job["path"])
            res = await client.chat.completions.create(
                model=NEBIUS_VISION_MODEL,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:image/png;base64,{b64}"},
                            }
                        ],
                    },
                ],
                max_tokens=400,  # Reduced from 800 for speed
            )

            content = res.choices[0].message.content

            # Clean response - fix control characters and common issues
            clean_content = content
            # Remove markdown code blocks
            clean_content = re.sub(r"```json|```", "", clean_content).strip()
            # Remove invalid control characters (keep newlines, tabs)
            clean_content = re.sub(
                r"[\x00-\x08\x0b\x0c\x0e-\x1f\x1e\x1f]", "", clean_content
            )
            # Fix unterminated strings
            if clean_content.count('"') % 2 != 0:
                # Find last complete field and truncate
                last_brace = clean_content.rfind("}")
                if last_brace > 0:
                    clean_content = clean_content[: last_brace + 1]

            try:
                extracted = json.loads(clean_content)
            except json.JSONDecodeError as je:
                # Fallback: extract title from content using regex
                extracted = {
                    "title": "Extraction Failed",
                    "company": "",
                    "location": "",
                    "job_type": "",
                    "deadline": "",
                    "salary": "",
                    "experience": "",
                    "skills": "",
                }
                # Try to salvage title using regex
                title_match = re.search(r'"title"\s*:\s*"([^"]+)', content)
                if title_match:
                    extracted["title"] = title_match.group(1)[:80]

            stats["ai_processed"] += 1
            print(f"  ✅ [AI] Extracted: {extracted.get('title', 'N/A')[:30]}")

            job_data = {
                "title": extracted.get("title", job.get("title", "")),
                "company": extracted.get("company", ""),
                "location": extracted.get("location", ""),
                "job_type": extracted.get("job_type", ""),
                "deadline": extracted.get("deadline", ""),
                "salary": extracted.get("salary", ""),
                "experience": extracted.get("experience", ""),
                "skills": extracted.get("skills", ""),
                "requirements": extracted.get("requirements", ""),
                "responsibilities": extracted.get("responsibilities", ""),
                "benefits": extracted.get("benefits", ""),
                "url": job.get("url", ""),
            }

            # Emit SSE event for THIS single job immediately
            print(f"  📡 [SSE] Emit for s_id={s_id}, u_id={u_id}")
            try:
                await job_queue.on_jobs_found(s_id, 1, [job_data])
                print(f"  📡 [SSE] Streaming: {job_data.get('title', '')[:25]}")
            except Exception as e:
                print(f"  ⚠️ [SSE] Error: {e}")

            return job_data

        except Exception as e:
            stats["errors"] += 1
            print(f"  ❌ [AI] Error on {job_name}: {e}")
            return {
                "title": job.get("title", ""),
                "company": "",
                "location": "",
                "job_type": "",
                "deadline": "",
                "salary": "",
                "experience": "",
                "skills": "",
                "requirements": "",
                "responsibilities": "",
                "benefits": "",
                "url": job.get("url", ""),
            }


async def capture_job(context, url: str, browser_sem: asyncio.Semaphore) -> dict | None:
    async with browser_sem:
        job_id = url.split("/")[-1].split("?")[0]

        page = await context.new_page()

        async def block_ads(route):
            if any(d in route.request.url for d in BLOCKED_RESOURCES):
                await route.abort()
            else:
                await route.continue_()

        await page.route("**/*", block_ads)

        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await asyncio.sleep(1)  # Reduced from 2s for speed

            # Default title until AI extracts it
            title = "Unknown Role"
            h1_elements = await page.locator("h1").all()
            for h1 in h1_elements:
                txt = await h1.inner_text()
                if (
                    txt.strip()
                    and len(txt) > 3
                    and not any(
                        x in txt.lower()
                        for x in ["partners", "insights", "bdjobs", "login", "sign in"]
                    )
                ):
                    title = txt.strip()
                    break
            # Fallback: try job-title class or role-title
            if title == "Unknown Role":
                try:
                    role_elem = await page.locator(
                        ".job-title, .role-title, [class*='title']"
                    ).first()
                    if role_elem:
                        txt = await role_elem.inner_text()
                        if txt and len(txt) > 3:
                            title = txt.strip()
                except:
                    pass

            SCREENSHOT_DIR.mkdir(exist_ok=True)
            path = str(SCREENSHOT_DIR / f"{job_id}.png")
            await page.screenshot(path=path, full_page=True)

            stats["captured"] += 1
            print(f"  📸 [Browser] Captured: {title[:40]}")

            await page.close()
            return {"id": job_id, "url": url, "path": path, "title": title}

        except Exception as e:
            await page.close()
            print(f"  ❌ [Browser] Failed: {url[:50]} - {e}")
            return None


async def run(
    query: str,
    location: str = "",
    max_jobs: int = MAX_JOBS,
    search_id: int = 0,
    user_id: int = 0,
) -> dict:
    """Main entry point - runs the bdjobs vision scraper."""

    print(f"\n🤖 [BDJobs Scraper] Starting for: '{query}'")

    start_time = time.time()
    jobs = []
    status = "success"

    try:
        # Initialize OpenAI client
        client = AsyncOpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/", api_key=NEBIUS_API_KEY
        )

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                viewport={"width": 1280, "height": 900},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
            )

            # Search page - skip ad blocking for simplicity/ stability
            search_page = await context.new_page()

            print(f"  🔍 [BDJobs] Navigating to search...")
            await search_page.goto(
                "https://bdjobs.com/h/", wait_until="domcontentloaded", timeout=60000
            )

            # Wait for and fill search
            await search_page.wait_for_selector("input[type='text']", timeout=15000)
            await search_page.fill("input[type='text']", query)
            await search_page.press("input[type='text']", "Enter")

            print(f"  ⏳ [BDJobs] Waiting for results...")
            await asyncio.sleep(8)

            # Debug: count all links on page
            all_link_count = await search_page.locator("a").count()
            print(f"  🔗 [BDJobs] Total links on page: {all_link_count}")

            # Get page title for debug
            title = await search_page.title()
            print(f"  📄 [BDJobs] Page title: {title}")

            # Try to filter for "Most Recent" - look for sort/filter dropdown
            try:
                # Look for sort dropdown or "Most Recent" option
                recent_btn = await search_page.locator(
                    "text=Most Recent,text=Newest,text=Recent"
                ).first()
                if await recent_btn.is_visible(timeout=3000):
                    await recent_btn.click()
                    print(f"  📅 [BDJobs] Filtered: Most Recent")
                    await asyncio.sleep(2)
            except Exception:
                pass  # Filter not found, continue anyway

            # Extract job links
            job_links = set()
            links = await search_page.locator("a[href*='/h/details/']").all()
            for a in links:
                href = await a.get_attribute("href")
                if href:
                    url = (
                        "https://bdjobs.com" + href
                        if not href.startswith("http")
                        else href
                    )
                    job_links.add(url.split("?")[0])

            links_list = list(job_links)[:max_jobs]
            stats["total_found"] = len(links_list)

            print(f"  🎯 [BDJobs] Found {len(links_list)} jobs")

            if not links_list:
                print("  ⚠️ [BDJobs] No jobs found")
                await browser.close()
                return {"total": 0, "status": "failed", "jobs": [], "path": ""}

            await search_page.close()

            # Capture job pages in parallel
            browser_sem = asyncio.Semaphore(MAX_BROWSER_CONCURRENCY)
            capture_tasks = [
                capture_job(context, url, browser_sem) for url in links_list
            ]
            captured_results = await asyncio.gather(*capture_tasks)

            valid_jobs = [j for j in captured_results if j]
            print(f"  📸 [BDJobs] Captured {len(valid_jobs)} job pages")

            if valid_jobs:
                # Extract with AI vision - emit SSE after each job completes
                ai_sem = asyncio.Semaphore(MAX_AI_CONCURRENCY)
                ai_tasks = [
                    process_with_ai(job, client, ai_sem, search_id, user_id)
                    for job in valid_jobs
                ]
                jobs = await asyncio.gather(*ai_tasks)

                print(f"  ✅ [BDJobs] Extracted {len(jobs)} jobs with AI")

                # Save to database (SSE already emitted per-job above)
                if search_id and user_id and jobs:
                    try:
                        # save_jobs_to_db handles duplicates, skip if already added by incremental saves
                        print(f"  💾 [BDJobs] Jobs saved to DB (incremental)")
                    except Exception as e:
                        print(f"  ⚠️ [BDJobs] DB save error (non-fatal): {e}")

            await browser.close()

    except Exception as e:
        status = "failed"
        print(f"  ❌ [BDJobs] Error: {e}")

    finally:
        # Cleanup screenshots
        if SCREENSHOT_DIR.exists():
            shutil.rmtree(SCREENSHOT_DIR)
            print(f"  🧹 [BDJobs] Cleaned up screenshots")

    elapsed = time.time() - start_time

    # Save to JSON
    safe_q = "".join(c if c.isalnum() else "_" for c in query)[:40]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = str(OUTPUT_DIR / f"bdjobs_{safe_q}_{ts}.json")

    data = {
        "meta": {
            "query": query,
            "search_id": search_id,
            "user_id": user_id,
            "timestamp": datetime.now().isoformat(),
            "total_found": len(jobs),
            "status": status,
            "elapsed_seconds": round(elapsed, 2),
        },
        "jobs": jobs,
    }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n  📊 [BDJobs] Done in {elapsed:.1f}s | {len(jobs)} jobs | {output_path}")

    return {
        "total": len(jobs),
        "status": status,
        "path": output_path,
        "jobs": jobs,
    }


if __name__ == "__main__":
    import sys

    q = sys.argv[1] if len(sys.argv) > 1 else input("Query: ").strip()
    loc = sys.argv[2] if len(sys.argv) > 2 else ""
    max_j = int(sys.argv[3]) if len(sys.argv) > 3 else 30

    result = asyncio.run(run(q, loc, max_j))
    print(result)
