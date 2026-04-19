"""
BD Tech Jobs Agent — SaaS Edition
===================================
Refactored to use BaseJobAgent.
Scrapes https://www.bdtechjobs.com

Uses the site's internal JSON API (/api/jobs) for reliable structured data extraction.
"""

import json
from urllib.parse import quote_plus
from .base_agent import BaseJobAgent, SITE_CONFIG, ActionResult

NAME = "bdtechjobs"
LABEL = "BD Tech Jobs"


class BDTechJobsAgent(BaseJobAgent):
    """BD Tech Jobs scraping agent with API-based extraction."""

    def __init__(
        self,
        query: str,
        location: str,
        max_jobs: int,
        search_id: int = 0,
        user_id: int = 0,
    ):
        super().__init__(
            query,
            location,
            max_jobs,
            search_id,
            user_id,
            site_config=SITE_CONFIG["bdtechjobs"],
        )
        # Add site-specific extraction tool (overrides generic HTML scraping)
        self._setup_api_extraction_tool()

    def _build_task(self) -> str:
        # Encode query and location for safe URL usage
        q = quote_plus(self.query)
        loc = quote_plus(self.location) if self.location else ""
        loc_str = f"&location={loc}" if loc else ""
        nav_url = f"https://www.bdtechjobs.com?search={q}{loc_str}"
        return (
            f"1. Navigate to {nav_url}\n"
            f"2. Wait 5 seconds for page to load\n"
            f"3. Use 'extract_jobs_from_api' to fetch job data from the API\n"
            f"4. Save the jobs by calling 'save_jobs' with batches of up to 5 jobs\n"
            f"5. For EACH saved job (up to {self.max_jobs} total), navigate DIRECTLY to its URL using 'go to <url>'\n"
            f"6. On the job detail page, call 'extract_job_details' to get full info (requirements, responsibilities, benefits, skills, education)\n"
            f"7. Call 'save_jobs' again to store the enhanced data\n"
            f"8. After processing each job, return to the search results page or navigate to the next job URL\n"
            f"9. Continue until {self.max_jobs} jobs are collected or all saved jobs processed\n"
            f"10. done(success=True)"
        )

    def _setup_api_extraction_tool(self) -> None:
        """Add a custom extraction tool that fetches data from bdtechjobs.com's JSON API."""

        @self.tools.action(
            description=(
                "Fetch structured job data directly from bdtechjobs.com API. "
                "Returns JSON array with title, company, location, job_type, deadline, "
                "salary, experience, skills, and other fields. "
                "Use this INSTEAD of extract_jobs_via_js for bdtechjobs.com."
            )
        )
        async def extract_jobs_from_api(browser_session) -> ActionResult:
            # Build URL-encoded query parameters
            search_param = quote_plus(self.query)
            location_param = quote_plus(self.location) if self.location else None
            params = f"search={search_param}"
            if location_param:
                params += f"&location={location_param}"

            js_code = f"""() => {{
                try {{
                    return fetch('/api/jobs?{params}')
                        .then(r => {{
                            if (!r.ok) throw new Error('HTTP ' + r.status);
                            return r.json();
                        }})
                        .then(data => {{
                            const jobs = (data.jobs || data || []).slice(0, 20);
                            return JSON.stringify(jobs.map(j => ({{
                                title: j.designation || '',
                                url: 'https://www.bdtechjobs.com/jobs/' + j.id,
                                company: j.companyName || '',
                                location: j.location || '',
                                job_type: j.jobType || '',
                                deadline: j.applicationDeadline || '',
                                salary: j.salary || '',
                                experience: j.experienceYears || '',
                                requirements: '',
                                responsibilities: '',
                                benefits: '',
                                skills: (j.requiredSkills || []).join(', '),
                                education: '',
                                company_info: '',
                                industry: (j.jobCategory || []).join(', ')
                            }})));
                        }})
                        .catch(err => JSON.stringify({{error: err.message}}));
                }} catch(e) {{
                    return JSON.stringify({{error: e.message}});
                }}
            }}"""
            try:
                page = await browser_session.get_current_page()
                raw = await page.evaluate(js_code)
                # raw is a JSON string
                if isinstance(raw, str):
                    if raw.startswith("["):
                        return ActionResult(extracted_content=raw)
                    elif raw.startswith("{"):
                        try:
                            err = json.loads(raw)
                            if "error" in err:
                                print(f"[extract_jobs_from_api] Error: {err['error']}")
                                return ActionResult(extracted_content="[]")
                        except:
                            pass
                return ActionResult(extracted_content="[]")
            except Exception as e:
                print(f"[extract_jobs_from_api] Exception: {e}")
                return ActionResult(error=f"API extraction failed: {e}")


async def run(
    query: str,
    location: str = "",
    max_jobs: int = 50,
    search_id: int = 0,
    user_id: int = 0,
) -> dict:
    return await BDTechJobsAgent(
        query=query,
        location=location,
        max_jobs=max_jobs,
        search_id=search_id,
        user_id=user_id,
    ).run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run(query="software engineer", max_jobs=20))
