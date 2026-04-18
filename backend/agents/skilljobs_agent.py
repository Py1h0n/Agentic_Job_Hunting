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
        """Minimal task - simple and fast."""
        return (
            f"1. Go to https://skill.jobs/browse-jobs?search={self.query.replace(' ', '%20')}\n"
            f"2. extract_jobs_via_js, then save_jobs.\n"
            f"3. done(success=True)"
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
