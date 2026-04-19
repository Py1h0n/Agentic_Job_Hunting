from pydantic import BaseModel, Field
from typing import List, Optional


class JobListing(BaseModel):
    """Schema for a single job listing."""

    title: str = Field(..., description="The job title")
    company: str = Field(..., description="The company name")
    location: str = Field(..., description="The job location (city/area)")
    job_type: str = Field(
        ..., description="Type of employment (e.g. Full-time, Contract)"
    )
    deadline: str = Field(..., description="Application deadline date")
    url: str = Field(..., description="URL to the job detail page (e.g. /job/123)")
    salary: Optional[str] = Field(None, description="Salary information if available")
    experience: Optional[str] = Field(
        None, description="Experience requirements if available"
    )
    # NEW: Enhanced fields for better matching accuracy
    requirements: Optional[str] = Field(
        None, description="Job requirements and qualifications"
    )
    responsibilities: Optional[str] = Field(
        None, description="Job responsibilities and duties"
    )
    benefits: Optional[str] = Field(None, description="Employee benefits and perks")
    skills: Optional[str] = Field(None, description="Required skills and technologies")
    education: Optional[str] = Field(None, description="Education requirements")
    company_info: Optional[str] = Field(None, description="Company overview and size")


class JobBatch(BaseModel):
    """Schema for a batch of extracted jobs."""

    jobs: List[JobListing] = Field(
        ..., description="List of job listings found on the page"
    )
