"""
ATB Jobs Job Search Agent — SaaS Edition
========================================
Refactored to use BaseJobAgent.
"""

from .base_agent import BaseJobAgent, SITE_CONFIG

NAME = "atb"
LABEL = "ATB Jobs"


class ATBJobsAgent(BaseJobAgent):
    """ATB Jobs job scraping agent."""

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
            site_config=SITE_CONFIG["atb"],
        )

    def _build_task(self) -> str:
        loc_str = f" in {self.location}" if self.location else ""
        return (
            f"1. Navigate to https://www.atb-jobs.com\n"
            f"2. Search for {self.query}{loc_str}\n"
            f"3. Wait 5 seconds for results\n"
            f"4. Use 'extract_jobs_via_js' to extract ALL AVAILABLE job data - extract: title, company, location, job_type, deadline, salary, experience, requirements, responsibilities, benefits, skills, education.\n"
            f"5. For the first 5 jobs from that list, call 'save_jobs' with complete data.\n"
            f"6. If more than 5 jobs were found, call 'save_jobs' again with the NEXT 5 jobs (max 5 per call).\n"
            f"7. Click on EACH job to visit its detail page, use 'extract_job_details' to get full information including requirements, responsibilities, benefits, skills, education.\n"
            f"8. After extracting details, call 'save_jobs' again to save the enhanced job data.\n"
            f"9. Scroll down and repeat until you have {self.max_jobs} jobs total.\n"
            f"10. done(success=True)"
        )


async def run(
    query: str,
    location: str = "",
    max_jobs: int = 50,
    search_id: int = 0,
    user_id: int = 0,
) -> dict:
    return await ATBJobsAgent(
        query=query,
        location=location,
        max_jobs=max_jobs,
        search_id=search_id,
        user_id=user_id,
    ).run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run(query="software engineer", max_jobs=20))
