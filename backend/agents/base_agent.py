"""
Base Job Agent — Shared logic for browser-use based job scraping agents.
============================================================================
All 6 browser-use agents (bdjobs, skilljobs, jobmedia, nextjobz, niyog, atb)
share identical logic for:
  - URL validation
  - Job normalization
  - Deduplication
  - File I/O
  - Parser
  - on_step_end hook
  - Browser/LLM setup

Subclasses only implement site-specific: _build_task(), FIELDS, NAME, LABEL
"""

import asyncio
import json
import os
import random
import re
from abc import abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("TIMEOUT_NavigateToUrlEvent", "60.0")
os.environ.setdefault("TIMEOUT_BrowserStateRequestEvent", "60.0")
os.environ.setdefault("TIMEOUT_NavigationCompleteEvent", "60.0")
os.environ.setdefault("TIMEOUT_ClickElementEvent", "30.0")
os.environ.setdefault("TIMEOUT_ScrollEvent", "20.0")

from browser_use import Agent, Tools, ActionResult, Browser
from browser_use.llm.openai.chat import ChatOpenAI
from dotenv import load_dotenv

from .schemas import JobBatch
import sys

sys.path.append(str(Path(__file__).parent.parent))
from database import save_jobs_to_db
import job_queue

load_dotenv()

LLM_API_KEY = os.getenv("NEBIUS_API_KEY", "")
LLM_BASE_URL = "https://api.tokenfactory.nebius.com/v1/"
LLM_MODEL = os.getenv("NEBIUS_AGENT_MODEL", "Qwen/Qwen3-235B-A22B-Instruct-2507")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "results"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FIELDS = [
    "title",
    "company",
    "location",
    "url",
    "deadline",
    "job_type",
    "salary",
    "experience",
    "requirements",
    "responsibilities",
    "benefits",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]


SITE_CONFIG: dict[str, dict] = {
    "bdjobs": {
        "name": "bdjobs",
        "label": "BDJobs",
        "domains": ["*.bdjobs.com", "bdjobs.com"],
        "url_template": "https://bdjobs.com/h/jobs?qOT=&txtsearch={query}&lang=en",
        "url_with_location": "https://bdjobs.com/h/jobs?qOT=&txtsearch={query}&city={location}&lang=en",
    },
    "skilljobs": {
        "name": "skilljobs",
        "label": "Skill.jobs",
        "domains": ["*.skill.jobs", "skill.jobs"],
        "url_template": "https://skill.jobs/browse-jobs?search={query}",
        "url_with_location": "https://skill.jobs/browse-jobs?search={query}",
    },
    "jobmedia": {
        "name": "jobmedia",
        "label": "Job Media",
        "domains": ["*.jobmedia.com.bd", "jobmedia.com.bd"],
        "url_template": "https://www.jobmedia.com.bd",
        "url_with_location": "https://www.jobmedia.com.bd",
    },
    "nextjobz": {
        "name": "nextjobz",
        "label": "NextJobz",
        "domains": ["*.nextjobz.com.bd", "nextjobz.com.bd"],
        "url_template": "https://www.nextjobz.com.bd",
        "url_with_location": "https://www.nextjobz.com.bd",
    },
    "niyog": {
        "name": "niyog",
        "label": "Niyog",
        "domains": ["*.niyog.co", "niyog.co"],
        "url_template": "https://www.niyog.co",
        "url_with_location": "https://www.niyog.co",
    },
    "atb": {
        "name": "atb",
        "label": "ATB Jobs",
        "domains": ["*.atb-jobs.com", "atb-jobs.com"],
        "url_template": "https://www.atb-jobs.com",
        "url_with_location": "https://www.atb-jobs.com",
    },
}


class BaseJobAgent:
    """
    Base class for browser-use job scraping agents.

    Subclasses implement:
      - _build_task() -> str (site-specific task prompt)
      - FIELDS (list of field names)
      - NAME (str)
      - LABEL (str)
    """

    def __init__(
        self,
        query: str,
        location: str,
        max_jobs: int,
        search_id: int = 0,
        user_id: int = 0,
        site_config: dict | None = None,
    ):
        self.query = query
        self.location = location
        self.max_jobs = max_jobs
        self.search_id = search_id
        self.user_id = user_id
        self.site_config = site_config or SITE_CONFIG.get("bdjobs")

        self.accumulated_jobs: list[dict] = []

        safe_q = "".join(c if c.isalnum() else "_" for c in query)[:40]
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_s{search_id}" if search_id else ""
        self.output_path = str(OUTPUT_DIR / f"jobs_{safe_q}_{ts}{suffix}.json")

        self.tools = Tools()
        self._setup_save_jobs_tool()
        self._setup_extraction_tool()

    def _setup_extraction_tool(self) -> None:
        @self.tools.action(
            description=(
                "Extract job data from the current page using high-performance Javascript. "
                "Use this INSTEAD of manually reading the page if it's very large. "
                "Returns a JSON array of job objects found on the page."
            )
        )
        async def extract_jobs_via_js(browser_session) -> ActionResult:
            js_code = """() => {
                const jobs = [];
                const seen = new Set();
                const patterns = ['/job/', '/jobs/', '/vacancy/', '/career/', '/position/', '/circular/', '/opening/'];
                const links = document.querySelectorAll('a[href]');
                for (const link of links) {
                    const href = link.getAttribute('href') || '';
                    const lhref = href.toLowerCase();
                    const isJobLink = patterns.some(p => lhref.includes(p));
                    if (!isJobLink) continue;
                    const title = (link.innerText || '').trim().split('\\n')[0].trim();
                    if (title.length < 5 || seen.has(href)) continue;
                    seen.add(href);
                    const card = link.closest('div, li, article, section, tr');
                    const cardText = card ? card.innerText : '';
                    const lines = cardText.split('\\n').map(l => l.trim()).filter(l => l.length > 0);
                    jobs.push({
                        title: title,
                        url: href,
                        company: lines.length > 1 ? lines[1].substring(0, 80) : '',
                        location: lines.length > 2 ? lines[2].substring(0, 80) : ''
                    });
                    if (jobs.length >= 30) break;
                }
                return JSON.stringify(jobs);
            }"""
            try:
                page = await browser_session.get_current_page()
                raw = await page.evaluate(js_code)
                if isinstance(raw, str) and raw.startswith("["):
                    return ActionResult(extracted_content=raw)
                return ActionResult(extracted_content="[]")
            except Exception as e:
                print(f"[extract_jobs_via_js] Error: {e}")
                return ActionResult(error=f"JS extraction failed: {e}")

    def _setup_save_jobs_tool(self) -> None:
        @self.tools.action(
            description=(
                "CRITICAL: Save job listings to database and continue. "
                "MUST be called after EVERY extract action with ALL jobs found. "
                "Input: JSON array of job objects with fields: title, company, location, job_type, deadline, url"
            ),
            # No allowed_domains - always available so agent can call it
        )
        async def save_jobs(batch: Any, browser_session) -> ActionResult:
            jobs_list = []

            # 1. Direct JobBatch object (if using output_model_schema)
            if hasattr(batch, "jobs"):
                jobs_list = []
                for j in batch.jobs:
                    if hasattr(j, "model_dump"):
                        jobs_list.append(j.model_dump())
                    elif hasattr(j, "dict"):
                        jobs_list.append(j.dict())
                    else:
                        jobs_list.append(j)
            # 2. JSON array (list)
            elif isinstance(batch, list):
                jobs_list = batch
            # 3. Dict with 'jobs' key
            elif isinstance(batch, dict):
                jobs_list = batch.get("jobs", [])
            # 4. JSON string fallback
            elif isinstance(batch, str):
                try:
                    p = json.loads(batch)
                    jobs_list = (
                        p.get("jobs", [])
                        if isinstance(p, dict)
                        else (p if isinstance(p, list) else [])
                    )
                except:
                    pass

            # Handle string list like ["Job Title - /job/12345", ...]
            if jobs_list and all(isinstance(j, str) for j in jobs_list):
                parsed = []
                for job_str in jobs_list:
                    if not job_str:
                        continue
                    # Try to parse as JSON first
                    job_str = job_str.strip()

                    # Try JSON parse
                    try:
                        if job_str.startswith("[") or job_str.startswith("{"):
                            parsed_json = json.loads(job_str)
                            if isinstance(parsed_json, list):
                                jobs_list = parsed_json
                                break
                            elif isinstance(parsed_json, dict):
                                jobs_list = [parsed_json]
                                break
                    except:
                        pass

                    # Remove leading dash and space if present
                    if job_str.startswith("- "):
                        job_str = job_str[2:]

                    # Match title and URL - the URL always ends the string in /job/XXX or /jobs/XXX
                    match = re.search(r"(.+?)\s*[-–]\s*(/job/\d+)", job_str)
                    if match:
                        title = match.group(1).strip()
                        url = match.group(2).strip()
                        if title and url:
                            parsed.append(
                                {
                                    "title": title,
                                    "url": url,
                                    "company": "",
                                    "location": "",
                                }
                            )
                            print(f"[save_jobs] Parsed: {title} -> {url}")
                    else:
                        # Fallback: try to find just the job ID pattern
                        url_match = re.search(r"(/job/\d+)", job_str)
                        if url_match:
                            url = url_match.group(1)
                            # Title is everything before the URL
                            title = (
                                job_str[: url_match.start()]
                                .strip()
                                .rstrip("- ")
                                .strip()
                            )
                            if title:
                                parsed.append(
                                    {
                                        "title": title,
                                        "url": url,
                                        "company": "",
                                        "location": "",
                                    }
                                )
                                print(f"[save_jobs] Fallback parsed: {title} -> {url}")
                if not jobs_list:  # Only set jobs_list to parsed if we didn't find JSON
                    jobs_list = parsed
                print(f"[save_jobs] Converted {len(jobs_list)} items to dicts")

            # Log what we're working with
            if jobs_list:
                print(f"[save_jobs] Processing {len(jobs_list)} jobs")
                # Print first job to see structure
                if jobs_list[0]:
                    print(f"[save_jobs] First job sample: {str(jobs_list[0])[:200]}")

            if not jobs_list:
                return ActionResult(
                    extracted_content="No jobs were provided to save.",
                    include_extracted_content_only_once=True,
                )

            self._append_to_json(jobs_list)
            added = self._merge_jobs(jobs_list)
            if added:
                normalized = [
                    j
                    for j in self.accumulated_jobs
                    if j.get("url") in [jo.get("url") for jo in jobs_list]
                ]
                # Save to database
                save_jobs_to_db(self.search_id, self.user_id, normalized)

                # Try to notify via queue using the running event loop
                try:
                    # Get the currently running event loop
                    loop = asyncio.get_running_loop()

                    # Schedule the async notification to run in the background
                    # This will work because we're inside an async function
                    asyncio.ensure_future(
                        job_queue.on_jobs_found(self.search_id, added, normalized)
                    )
                    print(
                        f"[save_jobs] Scheduled live-stream notification for {added} jobs"
                    )
                except Exception as e:
                    # Notification is optional - jobs already saved to DB
                    print(f"[save_jobs] Notification skipped: {e}")

            self._flush_to_disk(status="running")
            total = len(self.accumulated_jobs)

            if total >= self.max_jobs:
                return ActionResult(
                    extracted_content=f"SAVED {added} jobs. LIMIT REACHED ({total}/{self.max_jobs}). "
                    f"IMPORTANT: Forget these jobs from memory. Call done(success=True) NOW.",
                    include_extracted_content_only_once=True,
                )
            return ActionResult(
                extracted_content=f"SAVED {added} jobs (total: {total}). "
                f"IMPORTANT: Forget these jobs from memory. Continue to next page.",
                include_extracted_content_only_once=True,
            )

    def _is_valid_job_url(self, url: str) -> bool:
        """Validate URL is a job detail page, not a search/browse page."""
        if not url:
            return False
        if url.startswith("#"):
            return False
        # Reject known non-job pages
        reject = [
            "/browse-jobs",
            "#job-",
            "/login",
            "/register",
            "/signup",
            "/about",
            "/contact",
        ]
        lower = url.lower()
        for r in reject:
            if r in lower:
                return False
        # Accept any URL with a job-like path segment
        accept = [
            "/job/",
            "/jobs/",
            "/vacancy/",
            "/career/",
            "/position/",
            "/circular/",
            "/opening/",
            "/details/",  # BDJobs uses /details/ for job pages
        ]
        for a in accept:
            if a in lower:
                return True
        # Accept any URL that starts with http (likely a full job page link)
        if url.startswith("http"):
            return True
        return False

    def _normalise(self, j: Any) -> dict | None:
        """Normalize job data: strip keys, fix URLs, validate."""
        if not isinstance(j, dict):
            return None

        cleaned = {k.lstrip("-").strip(): str(v or "").strip() for k, v in j.items()}

        # Handle alternate key names from LLM output
        # Title variations
        if not cleaned.get("title"):
            cleaned["title"] = (
                cleaned.get("job_title")
                or cleaned.get("JobTitle")
                or cleaned.get("Job Title")
                or cleaned.get("title")
                or cleaned.get("Title")
                or cleaned.get("jobTitle")
                or ""
            )

        # URL variations
        if not cleaned.get("url"):
            cleaned["url"] = (
                cleaned.get("job_url")
                or cleaned.get("JobURL")
                or cleaned.get("Job URL")
                or cleaned.get("url")
                or cleaned.get("URL")
                or cleaned.get("jobUrl")
                or cleaned.get("link")
                or cleaned.get("href")
                or ""
            )

        # Company variations
        if not cleaned.get("company"):
            cleaned["company"] = (
                cleaned.get("company_name")
                or cleaned.get("CompanyName")
                or cleaned.get("Company")
                or cleaned.get("companyName")
                or cleaned.get("employer")
                or cleaned.get("Employer")
                or ""
            )

        # Location variations
        if not cleaned.get("location"):
            cleaned["location"] = (
                cleaned.get("location")
                or cleaned.get("Location")
                or cleaned.get("city")
                or cleaned.get("City")
                or cleaned.get("area")
                or cleaned.get("Area")
                or ""
            )

        # Job type variations
        if not cleaned.get("job_type"):
            cleaned["job_type"] = (
                cleaned.get("job_type")
                or cleaned.get("JobType")
                or cleaned.get("jobType")
                or cleaned.get("type")
                or cleaned.get("type")
                or ""
            )

        # Deadline variations
        if not cleaned.get("deadline"):
            cleaned["deadline"] = (
                cleaned.get("deadline")
                or cleaned.get("Deadline")
                or cleaned.get("application_deadline")
                or cleaned.get("last_date")
                or cleaned.get("closing_date")
                or ""
            )

        title = cleaned.get("title", "").strip()
        if not title:
            return None
        url = cleaned.get("url", "")

        if url and not self._is_valid_job_url(url):
            return None

        if url:
            if url.startswith("http"):
                # Keep original URL but ensure it's valid
                cleaned["url"] = url
            elif url.startswith("/"):
                # Convert relative /job/123 to absolute https://site.com/job/123
                cleaned["url"] = self._resolve_relative_url(url)
            else:
                cleaned["url"] = url

        # Ensure we have at least title and url (location/company can be empty)
        return {
            "title": title,
            "url": cleaned.get("url", ""),
            "company": cleaned.get("company", ""),
            "location": cleaned.get("location", ""),
            "deadline": cleaned.get("deadline", ""),
            "job_type": cleaned.get("job_type", ""),
            "salary": cleaned.get("salary", ""),
            "experience": cleaned.get("experience", ""),
            "requirements": cleaned.get("requirements", ""),
            "responsibilities": cleaned.get("responsibilities", ""),
            "benefits": cleaned.get("benefits", ""),
        }

    def _resolve_relative_url(self, url: str) -> str:
        """Resolve relative URL to absolute based on site config."""
        domains = self.site_config.get("domains", [])
        site_name = self.site_config.get("name", "")

        domain_map = {
            "bdjobs": "https://bdjobs.com",
            "skilljobs": "https://skill.jobs",
            "jobmedia": "https://www.jobmedia.com.bd",
            "nextjobz": "https://www.nextjobz.com.bd",
            "niyog": "https://www.niyog.co",
            "atb": "https://www.atb-jobs.com",
        }

        base_url = domain_map.get(site_name, "https://bdjobs.com")

        # Clean the relative URL: /job/123 -> job/123
        clean_url = url.lstrip("/")

        # Ensure base_url ends with nothing before the slash
        base_url = base_url.rstrip("/")

        return f"{base_url}/{clean_url}"

    def _get_fields(self) -> list[str]:
        """Get field names - can be overridden by subclass."""
        return FIELDS

    def _merge_jobs(self, new_jobs: list[Any]) -> int:
        """Deduplicate and merge new jobs into accumulated list."""
        seen = {j.get("url") or j.get("title") for j in self.accumulated_jobs}
        added = 0
        for raw in new_jobs:
            j = self._normalise(raw)
            if not j:
                print(f"[_merge_jobs] Skipped - normalize returned None")
                continue
            key = j.get("url") or j.get("title")
            if key and key not in seen:
                self.accumulated_jobs.append(j)
                seen.add(key)
                added += 1
                print(f"[_merge_jobs] Added: {j.get('title')} with URL: {j.get('url')}")
        print(
            f"[_merge_jobs] Total added: {added}, accumulated: {len(self.accumulated_jobs)}"
        )
        return added

    def _flush_to_disk(self, status: str = "running") -> None:
        """Write accumulated jobs to JSON file."""
        data = {
            "meta": {
                "query": self.query,
                "search_id": self.search_id,
                "user_id": self.user_id,
                "timestamp": datetime.now().isoformat(),
                "total_found": len(self.accumulated_jobs),
                "status": status,
            },
            "jobs": self.accumulated_jobs,
        }
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _append_to_json(self, jobs: list[dict]) -> None:
        """Append jobs to JSONL backup file."""
        json_backup = str(OUTPUT_DIR / f"jobs_backup_{self.search_id}.jsonl")
        try:
            with open(json_backup, "a", encoding="utf-8") as f:
                for job in jobs:
                    if isinstance(job, dict):
                        f.write(json.dumps(job, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[tool][s{self.search_id}] JSON backup error: {e}")

    def _load_from_disk(self) -> list[dict]:
        """Load jobs from disk as fallback."""
        if not Path(self.output_path).exists():
            return []
        try:
            with open(self.output_path) as f:
                return json.load(f).get("jobs", [])
        except Exception:
            return []

    @staticmethod
    def _try_parse_jobs(text: str) -> list[dict]:
        """Parse job data from LLM output using multiple strategies."""
        text = text.strip()

        # Strategy 1: Direct JSON array
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [x for x in parsed if isinstance(x, dict)]
            except Exception:
                pass

        # Strategy 2: JSON array in markdown
        m = re.search(r"\[[\s\S]*?\]", text)
        if m:
            try:
                parsed = json.loads(m.group())
                if isinstance(parsed, list):
                    return [x for x in parsed if isinstance(x, dict)]
            except Exception:
                pass

        # Strategy 3: JSON objects
        objects = []
        for obj_str in re.findall(r"\{[^{}]+\}", text, re.DOTALL):
            try:
                d = json.loads(obj_str)
                if isinstance(d, dict) and ("title" in d or "Title" in d):
                    objects.append(d)
            except Exception:
                pass
        if objects:
            return objects

        # Strategy 4: "- Title: /job/12345" format (common job extraction)
        jobs: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line.startswith("-"):
                continue
            line = line[1:].strip()  # Remove leading "-"

            # Match "Job Title: /job/12345" pattern
            m = re.match(r"^(.+?):\s*(/job/\d+)", line)
            if m:
                title = m.group(1).strip()
                url = m.group(2).strip()
                if title and url:
                    jobs.append(
                        {"title": title, "url": url, "company": "", "location": ""}
                    )
                    continue

            # Match "Title: Job Title\nURL: /job/12345" pattern
            m2 = re.match(r"^title\s*:\s*(.+)$", line, re.I)
            if m2:
                if jobs and not jobs[-1].get("title"):
                    jobs[-1]["title"] = m2.group(1).strip()
                elif not jobs or jobs[-1].get("title"):
                    jobs.append(
                        {
                            "title": m2.group(1).strip(),
                            "url": "",
                            "company": "",
                            "location": "",
                        }
                    )
                continue

            # Match "URL: /job/12345" pattern
            m3 = re.match(r"^url\s*:\s*(/job/\d+)", line, re.I)
            if m3 and jobs:
                jobs[-1]["url"] = m3.group(1).strip()

        if jobs:
            return [j for j in jobs if j.get("title")]

        # Strategy 5: Title: value\nCompany: value format
        jobs = []
        current: dict = {}
        for line in text.splitlines():
            line = line.strip()
            if re.match(r"^-\s+title\s*:", line, re.I):
                if current.get("title"):
                    jobs.append(current)
                current = {}
            m2 = re.match(r"^-?\s*(\w+)\s*:\s*(.+)$", line)
            if m2:
                key = m2.group(1).lower().strip()
                val = m2.group(2).strip()
                if val.lower() in ("null", "none", "n/a"):
                    val = ""
                current[key] = val
        if current.get("title"):
            jobs.append(current)
        return jobs

    async def _on_step_end(self, agent: Agent) -> None:
        """Hook called after each agent step - captures jobs from extracted content."""
        try:
            contents = agent.history.extracted_content()
            if contents:
                for content in reversed(contents):
                    if not content or not isinstance(content, str):
                        continue
                    jobs = self._try_parse_jobs(content)
                    if jobs:
                        added = self._merge_jobs(jobs)
                        if added:
                            print(
                                f"[hook][s{self.search_id}] Captured {added} from extracted_content"
                            )
                        break
            self._flush_to_disk(status="running")
        except Exception as e:
            print(f"[hook][s{self.search_id}] on_step_end error (non-fatal): {e}")

    @abstractmethod
    def _build_task(self) -> str:
        """Build the task prompt - must be implemented by subclass."""
        pass

    def _create_llm(self) -> ChatOpenAI:
        """Create the LLM client."""
        return ChatOpenAI(
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            temperature=0.0,
        )

    def _create_browser(self) -> Browser:
        """Create the browser with site-specific configuration."""
        user_agent = random.choice(USER_AGENTS)
        domains = self.site_config.get("domains", [])

        use_cloud = bool(os.getenv("BROWSER_USE_API_KEY"))

        if use_cloud:
            return Browser(
                use_cloud=True,
                allowed_domains=domains,
            )

        return Browser(
            headless=True,
            allowed_domains=domains,
            minimum_wait_page_load_time=3.0,
            wait_for_network_idle_page_load_time=2.0,
            wait_between_actions=1.0,
            paint_order_filtering=True,  # Optimize DOM tree
            user_agent=user_agent,
            enable_default_extensions=False,  # Disable to speed up
            viewport={"width": 1280, "height": 720},
            window_size={"width": 1280, "height": 720},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--disable-web-security",
                "--ignore-certificate-errors",
                "--disable-features=IsolateOrigins,site-per-process",  # Help with frame issues
            ],
        )

    async def run(self) -> dict:
        """Main entry point - runs the browser-use agent."""
        self._flush_to_disk(status="starting")

        llm = self._create_llm()
        browser = self._create_browser()

        domains = self.site_config.get("domains", [])
        site_name = self.site_config.get("label", "Job Site")

        agent = Agent(
            task=self._build_task(),
            llm=llm,
            browser=browser,
            tools=self.tools,
            output_model_schema=JobBatch,  # Enforce strict schema
            use_vision=False,
            use_thinking=False,  # Skip thinking for speed
            flash_mode=True,  # Fast mode - no evaluation overhead
            max_actions_per_step=3,  # More actions per turn for efficiency
            max_failures=3,
            final_response_after_failure=True,
            max_history_items=6,  # Minimum recommended
            step_timeout=90,
            llm_timeout=60,
            extend_system_message=self._get_system_message(site_name),
        )

        status = "success"
        try:
            history = await agent.run(max_steps=15, on_step_end=self._on_step_end)

            if not self.accumulated_jobs:
                final = history.final_result()
                if final and isinstance(final, str):
                    jobs_from_final = self._try_parse_jobs(final)
                    if jobs_from_final:
                        added = self._merge_jobs(jobs_from_final)
                        print(
                            f"[agent][s{self.search_id}] final_result() captured {added} jobs"
                        )
                if not self.accumulated_jobs and final:
                    try:
                        parsed = json.loads(final)
                        if isinstance(parsed, dict) and "jobs" in parsed:
                            added = self._merge_jobs(parsed["jobs"])
                            print(
                                f"[agent][s{self.search_id}] final_result() JSON object captured {added} jobs"
                            )
                    except Exception:
                        pass

            if not history.is_successful():
                status = "partial" if self.accumulated_jobs else "failed"

        except Exception as e:
            status = "partial" if self.accumulated_jobs else "failed"
            print(f"[agent][s{self.search_id}] Exception (non-fatal): {e}")

        if not self.accumulated_jobs:
            disk_jobs = self._load_from_disk()
            if disk_jobs:
                self.accumulated_jobs = disk_jobs
                status = "partial"
                print(
                    f"[agent][s{self.search_id}] Disk fallback loaded {len(self.accumulated_jobs)} jobs"
                )

        self._flush_to_disk(status=status)
        print(
            f"[agent][s{self.search_id}] Finished — {len(self.accumulated_jobs)} jobs | {status} | {self.output_path}"
        )

        return {
            "total": len(self.accumulated_jobs),
            "status": status,
            "path": self.output_path,
            "jobs": self.accumulated_jobs,
        }

    def _get_system_message(self, site_name: str) -> str:
        """Get the strict system message for the agent."""
        return (
            f"You are a job search agent on {site_name}. "
            "STRICT RULES:\n"
            "1. ALWAYS try to use 'extract_jobs_via_js' first to find job links. It is much faster and more reliable.\n"
            "2. Output ONLY RAW DATA or call tools. Never explain your actions.\n"
            "3. NEVER include comments, notes, thinking logs, or '_comment' fields.\n"
            "4. Extract MAX 5 jobs per batch. If 20 are found, call save_jobs 4 times (5 at a time).\n"
            "5. After calling save_jobs, FORGET previously extracted jobs to save memory.\n"
            '6. For missing fields, use empty string "".\n'
        )
