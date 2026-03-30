"""
BDJobs Job Search Agent — SaaS Edition
=======================================
Original: agent_up.py (all logic, fixes FIX-1 through FIX-8 preserved)
Change:   Module-level globals → BDJobsAgent class instance state.

WHY: The original uses module globals (_accumulated_jobs, _query_label,
_output_path, and the Tools() closure). Two concurrent users would share
those globals and corrupt each other's results.

FIX: Every stateful piece lives on `self`. Each call to run() creates
a fresh BDJobsAgent instance — fully isolated, no shared state.

The CLI at the bottom still works unchanged: python bdjobs_agent.py
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# FIX-8: env vars must be set before browser_use import
os.environ.setdefault("TIMEOUT_NavigateToUrlEvent",       "60.0")
os.environ.setdefault("TIMEOUT_BrowserStateRequestEvent", "60.0")
os.environ.setdefault("TIMEOUT_NavigationCompleteEvent",  "60.0")
os.environ.setdefault("TIMEOUT_ClickElementEvent",        "30.0")
os.environ.setdefault("TIMEOUT_ScrollEvent",              "20.0")

from browser_use import Agent, Tools, ActionResult, Browser
from browser_use.llm.openai.chat import ChatOpenAI
from dotenv import load_dotenv

load_dotenv()

# Constants — read once, never mutated
LLM_API_KEY  = os.getenv("NEBIUS_API_KEY", "")
LLM_BASE_URL = os.getenv("ZAI_BASE_URL",   "https://api.tokenfactory.nebius.com/v1/")
LLM_MODEL    = os.getenv("ZAI_MODEL",      "openai/gpt-oss-20b")
OUTPUT_DIR   = Path(os.getenv("OUTPUT_DIR", "results"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

FIELDS = ["title", "company", "location", "deadline", "job_type", "url", "salary", "experience"]

NAME  = "bdjobs"
LABEL = "BDJobs"


class BDJobsAgent:
    """
    One instance per search. Holds all state that was previously global:
      _accumulated_jobs  -> self.accumulated_jobs
      _query_label       -> self.query
      _output_path       -> self.output_path
      tools (Tools())    -> self.tools  (closure captures self, not globals)
    """

    def __init__(self, query: str, location: str, max_jobs: int,
                 search_id: int = 0, user_id: int = 0):
        self.query     = query
        self.location  = location
        self.max_jobs  = max_jobs
        self.search_id = search_id
        self.user_id   = user_id

        self.accumulated_jobs: list[dict] = []

        # Output path scoped to search_id — concurrent runs never collide on disk
        safe_q = "".join(c if c.isalnum() else "_" for c in query)[:40]
        ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = f"_s{search_id}" if search_id else ""
        self.output_path = str(OUTPUT_DIR / f"jobs_{safe_q}_{ts}{suffix}.json")

        # Fresh Tools() per instance — closure captures self, not module globals
        # FIX-1: list[dict] not list[JobListing]
        # FIX-6: is_done=True stops agent cleanly after saving
        # FIX-7: include_extracted_content_only_once keeps context small
        self.tools = Tools()

        @self.tools.action(
            description=(
                "Save ALL job listings you extracted from the current page. "
                "Call this after extracting jobs. Pass the complete list. "
                "Missing fields are fine — use empty string."
            ),
            allowed_domains=["*.bdjobs.com", "bdjobs.com"],
        )
        def save_jobs(jobs: list[dict[str, Any]]) -> ActionResult:
            added = self._merge_jobs(jobs)
            self._flush_to_disk(status="running")
            total = len(self.accumulated_jobs)
            print(f"[tool][s{self.search_id}] save_jobs +{added} new | {total} total")
            return ActionResult(
                extracted_content=f"Saved {added} new jobs. Running total: {total}.",
                include_extracted_content_only_once=True,
                long_term_memory=f"Jobs saved: {total}. Call done(success=True) now.",
            )

    # ── Normalise ────────────────────────────────────────────────────────────

    def _normalise(self, j: Any) -> dict | None:
        """
        FIX-5: relative URLs made absolute.
        Strips dash-prefixed keys, coerces values to str.
        Returns None when title is absent.
        """
        if not isinstance(j, dict):
            return None
        cleaned = {k.lstrip("-").strip(): str(v or "").strip() for k, v in j.items()}
        title = cleaned.get("title", "").strip()
        if not title:
            return None
        url = cleaned.get("url", "")
        if url and url.startswith("/"):
            cleaned["url"] = "https://bdjobs.com" + url
        return {f: cleaned.get(f, "") for f in FIELDS}

    def _merge_jobs(self, new_jobs: list[Any]) -> int:
        seen  = {j.get("url") or j.get("title") for j in self.accumulated_jobs}
        added = 0
        for raw in new_jobs:
            j = self._normalise(raw)
            if not j:
                continue
            key = j.get("url") or j.get("title")
            if key and key not in seen:
                self.accumulated_jobs.append(j)
                seen.add(key)
                added += 1
        return added

    # ── Disk I/O ─────────────────────────────────────────────────────────────

    def _flush_to_disk(self, status: str = "running") -> None:
        data = {
            "meta": {
                "query":       self.query,
                "search_id":   self.search_id,
                "user_id":     self.user_id,
                "timestamp":   datetime.now().isoformat(),
                "total_found": len(self.accumulated_jobs),
                "status":      status,
            },
            "jobs": self.accumulated_jobs,
        }
        with open(self.output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _load_from_disk(self) -> list[dict]:
        """Last-resort: reload jobs written by _flush_to_disk after crash."""
        if not Path(self.output_path).exists():
            return []
        try:
            with open(self.output_path) as f:
                return json.load(f).get("jobs", [])
        except Exception:
            return []

    # ── Parser ───────────────────────────────────────────────────────────────

    @staticmethod
    def _try_parse_jobs(text: str) -> list[dict]:
        """
        FIX-4: Handle all extract output formats:
          Strategy 1 - clean JSON array:    [{"title": ...}, ...]
          Strategy 2 - embedded JSON:       some text [...] more text
          Strategy 3 - individual objects:  {"title": ...} {"title": ...}
          Strategy 4 - bullet list:         - title: X\n  company: Y
        """
        text = text.strip()

        # Strategy 1: clean JSON array
        if text.startswith("["):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [x for x in parsed if isinstance(x, dict)]
            except Exception:
                pass

        # Strategy 2: JSON array embedded in text
        m = re.search(r'\[[\s\S]*?\]', text)
        if m:
            try:
                parsed = json.loads(m.group())
                if isinstance(parsed, list):
                    return [x for x in parsed if isinstance(x, dict)]
            except Exception:
                pass

        # Strategy 3: individual JSON objects
        objects = []
        for obj_str in re.findall(r'\{[^{}]+\}', text, re.DOTALL):
            try:
                d = json.loads(obj_str)
                if isinstance(d, dict) and ("title" in d or "Title" in d):
                    objects.append(d)
            except Exception:
                pass
        if objects:
            return objects

        # Strategy 4: bullet/dash list — "- title: X\n  company: Y"
        jobs: list[dict] = []
        current: dict = {}
        for line in text.splitlines():
            line = line.strip()
            if re.match(r'^-\s+title\s*:', line, re.I):
                if current.get("title"):
                    jobs.append(current)
                current = {}
            m2 = re.match(r'^-?\s*(\w+)\s*:\s*(.+)$', line)
            if m2:
                key = m2.group(1).lower().strip()
                val = m2.group(2).strip()
                if val.lower() in ("null", "none", "n/a"):
                    val = ""
                current[key] = val
        if current.get("title"):
            jobs.append(current)
        return jobs

    # ── on_step_end hook ─────────────────────────────────────────────────────

    async def _on_step_end(self, agent: Agent) -> None:
        """
        FIX-4 + crash safety.
        Runs every step, captures jobs from extracted_content regardless of
        whether save_jobs was called, then flushes to disk.
        """
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
                            print(f"[hook][s{self.search_id}] Captured {added} from extracted_content")
                        break
            self._flush_to_disk(status="running")
        except Exception as e:
            print(f"[hook][s{self.search_id}] on_step_end error (non-fatal): {e}")

    # ── Task prompt ───────────────────────────────────────────────────────────

    def _build_task(self) -> str:
        loc_str = f" {self.location}" if self.location else ""
        return (
            f"1. Use navigate action to go to https://bdjobs.com\n"
            f"2. Find the search input box and use input action to type \"{self.query}{loc_str}\"\n"
            f"3. Use click action to click the Search button. "
            f"If it cannot be clicked, use send_keys \"Enter\" instead\n"
            f"4. Wait for the search results page to load\n"
            f"5. Use extract action with this exact prompt:\n"
            f"   Extract all job listings. Return a JSON array. Each item must have:\n"
            f"   title, company, location, deadline, job_type, url, salary, experience.\n"
            f"   If a field is not available use empty string. Return ONLY the JSON array.\n"
            f"6. Call save_jobs tool with the extracted list\n"
            f"7. Use done action with success=True"
        )

    # ── Main run ──────────────────────────────────────────────────────────────

    async def run(self) -> dict:
        self._flush_to_disk(status="starting")

        llm = ChatOpenAI(
            model=LLM_MODEL,
            api_key=LLM_API_KEY,
            base_url=LLM_BASE_URL,
            temperature=0.0,
        )

        browser = Browser(
            headless=True,
            allowed_domains=["*.bdjobs.com", "bdjobs.com"],
            minimum_wait_page_load_time=2.0,
            wait_for_network_idle_page_load_time=3.0,
        )

        agent = Agent(
            task=self._build_task(),
            llm=llm,
            browser=browser,
            tools=self.tools,
            # FIX-2: NO output_model_schema — $defs error breaks extract
            use_vision=False,
            flash_mode=True,
            max_actions_per_step=4,
            max_failures=5,
            final_response_after_failure=True,
            max_history_items=10,
            step_timeout=120,
            extend_system_message=(
                "You are a job search agent on BDJobs. "
                "Navigate, search, extract jobs as a JSON array, call save_jobs, then done. "
                "If a field is missing use empty string. Stay on bdjobs.com."
            ),
        )

        status = "success"
        try:
            history = await agent.run(max_steps=20, on_step_end=self._on_step_end)

            # FIX-3: history.final_result() fallback for done(data=...) payload
            if not self.accumulated_jobs:
                final = history.final_result()
                if final and isinstance(final, str):
                    jobs_from_final = self._try_parse_jobs(final)
                    if jobs_from_final:
                        added = self._merge_jobs(jobs_from_final)
                        print(f"[agent][s{self.search_id}] final_result() captured {added} jobs")
                if not self.accumulated_jobs and final:
                    try:
                        parsed = json.loads(final)
                        if isinstance(parsed, dict) and "jobs" in parsed:
                            added = self._merge_jobs(parsed["jobs"])
                            print(f"[agent][s{self.search_id}] final_result() JSON object captured {added} jobs")
                    except Exception:
                        pass

            if not history.is_successful():
                status = "partial" if self.accumulated_jobs else "failed"

        except Exception as e:
            status = "partial" if self.accumulated_jobs else "failed"
            print(f"[agent][s{self.search_id}] Exception (non-fatal): {e}")

        # Last resort: reload from disk if in-memory is still empty
        if not self.accumulated_jobs:
            disk_jobs = self._load_from_disk()
            if disk_jobs:
                self.accumulated_jobs = disk_jobs
                status = "partial"
                print(f"[agent][s{self.search_id}] Disk fallback loaded {len(self.accumulated_jobs)} jobs")

        self._flush_to_disk(status=status)
        print(f"[agent][s{self.search_id}] Finished — {len(self.accumulated_jobs)} jobs | {status} | {self.output_path}")

        return {
            "total":  len(self.accumulated_jobs),
            "status": status,
            "path":   self.output_path,
            "jobs":   self.accumulated_jobs,
        }


# ─── Registry entry point (called by agents/__init__.py) ─────────────────────

async def run(query: str, location: str = "", max_jobs: int = 50,
              search_id: int = 0, user_id: int = 0) -> dict:
    """Creates a fresh isolated BDJobsAgent per call — no shared state."""
    return await BDJobsAgent(
        query=query, location=location, max_jobs=max_jobs,
        search_id=search_id, user_id=user_id
    ).run()


# ─── CLI (identical behaviour to original agent_up.py) ───────────────────────

async def _cli():
    print("=" * 55)
    print("  BDJobs Job Search Agent")
    print("=" * 55)

    query    = input("Job title / keywords : ").strip()
    location = input("Location (leave blank for all) : ").strip()
    max_str  = input("Max jobs to fetch [50] : ").strip()
    max_jobs = int(max_str) if max_str.isdigit() else 50

    if not query:
        print("No query entered. Exiting.")
        sys.exit(1)

    print(f"\n[agent] Searching for '{query}'{f' in {location}' if location else ''}...\n")
    t0 = time.time()

    result = await run(query=query, location=location, max_jobs=max_jobs)
    elapsed = time.time() - t0

    print("\n" + "=" * 55)
    print(f"  Status  : {result['status']}")
    print(f"  Jobs    : {result['total']}")
    print(f"  Time    : {elapsed:.1f}s")
    print(f"  Output  : {result['path']}")
    print("=" * 55)

    if result["jobs"]:
        print("\nSample results:")
        for job in result["jobs"][:5]:
            print(f"  • {job.get('title')} — {job.get('company')} [{job.get('location')}]")


if __name__ == "__main__":
    asyncio.run(_cli())
