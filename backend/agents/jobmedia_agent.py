"""
Job Media Job Search Agent — SaaS Edition
==========================================
Refactored to use BaseJobAgent.
"""

from .base_agent import BaseJobAgent, SITE_CONFIG

NAME = "jobmedia"
LABEL = "Job Media"

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
    "company_info",
    "industry",
]


class JobMediaAgent(BaseJobAgent):
    """Job Media job scraping agent."""

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
            site_config=SITE_CONFIG["jobmedia"],
        )

    def _get_fields(self) -> list[str]:
        return FIELDS

    def _build_task(self) -> str:
        return (
            f"1. Navigate to https://www.jobmedia.com.bd/jobs\n"
            f"2. Wait 5 seconds for page to load fully\n"
            f"3. Use 'extract_jobs_via_js' to get all job links on the current page.\n"
            f"4. For the first 5 jobs from that list, call 'save_jobs'.\n"
            f"5. If more than 5 jobs were found, call 'save_jobs' again with the NEXT 5 jobs (max 5 per call).\n"
            f"6. Scroll down and repeat until you have {self.max_jobs} jobs total.\n"
            f"7. done(success=True)"
        )


async def run(
    query: str,
    location: str = "",
    max_jobs: int = 50,
    search_id: int = 0,
    user_id: int = 0,
) -> dict:
    return await JobMediaAgent(
        query=query,
        location=location,
        max_jobs=max_jobs,
        search_id=search_id,
        user_id=user_id,
    ).run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run(query="software engineer", max_jobs=20))
