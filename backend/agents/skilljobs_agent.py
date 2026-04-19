"""
Skill.jobs Job Search Agent — SaaS Edition
==========================================
Refactored to use BaseJobAgent.
"""

from .base_agent import BaseJobAgent, SITE_CONFIG

NAME = "skilljobs"
LABEL = "Skill.jobs"


class SkillJobsAgent(BaseJobAgent):
    """Skill.jobs job scraping agent."""

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
            site_config=SITE_CONFIG["skilljobs"],
        )

    def _build_task(self) -> str:
        loc_str = f" in {self.location}" if self.location else ""
        return (
            f"1. Navigate to https://skill.jobs/browse-jobs?search={self.query.replace(' ', '%20')}\n"
            f"2. Wait 5 seconds for page to fully load and render job listings.\n"
            f"3. Use 'extract_jobs_via_js' to extract ALL AVAILABLE job data from the current page - extract fields: title, company, location, job_type, deadline, salary, experience, requirements, responsibilities, benefits, skills, education.\n"
            f"4. For the first 5 jobs from that list, call 'save_jobs' with complete data.\n"
            f"5. If more than 5 jobs were found, call 'save_jobs' again with the NEXT 5 jobs (max 5 per call).\n"
            f"6. Click on EACH job to visit its detail page, use 'extract_job_details' to get full information including requirements, responsibilities, benefits, skills, education.\n"
            f"7. After extracting details, call 'save_jobs' again to save the enhanced job data.\n"
            f"8. Scroll down and repeat until you have {self.max_jobs} jobs total.\n"
            f"9. done(success=True)"
        )


async def run(
    query: str,
    location: str = "",
    max_jobs: int = 30,
    search_id: int = 0,
    user_id: int = 0,
) -> dict:
    return await SkillJobsAgent(
        query=query,
        location=location,
        max_jobs=max_jobs,
        search_id=search_id,
        user_id=user_id,
    ).run()


if __name__ == "__main__":
    import asyncio

    asyncio.run(run(query="software engineer", max_jobs=20))
