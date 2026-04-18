from pydantic import BaseModel, Field
from typing import List, Optional

class JobListing(BaseModel):
    """Schema for a single job listing."""
    title: str = Field(..., description="The job title")
    company: str = Field(..., description="The company name")
    location: str = Field(..., description="The job location (city/area)")
    job_type: str = Field(..., description="Type of employment (e.g. Full-time, Contract)")
    deadline: str = Field(..., description="Application deadline date")
    url: str = Field(..., description="URL to the job detail page (e.g. /job/123)")
    salary: Optional[str] = Field(None, description="Salary information if available")
    experience: Optional[str] = Field(None, description="Experience requirements if available")

class JobBatch(BaseModel):
    """Schema for a batch of extracted jobs."""
    jobs: List[JobListing] = Field(..., description="List of job listings found on the page")
