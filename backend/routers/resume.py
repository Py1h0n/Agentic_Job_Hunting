import base64
import json
import os
import re
import uuid
from collections import Counter
from pathlib import Path
from typing import Optional
from concurrent.futures import ThreadPoolExecutor

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from database import get_db
from auth import current_user

router = APIRouter(prefix="/api/resume", tags=["resume"])

ALLOWED_TYPES = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "application/pdf": "pdf",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
MAX_SIZE = 10 * 1024 * 1024  # 10MB

RESUME_DIR = Path(os.getenv("RESUME_DIR", "backend/resumes"))
RESUME_DIR.mkdir(parents=True, exist_ok=True)

# Central Model Configuration
RESUME_MODEL = os.getenv("NEBIUS_RESUME_MODEL", "google/gemma-3-27b-it")

RESUME_ANALYZER_PROMPT = """You are a resume analyzer. Analyze this resume and extract structured information.

Return ONLY a JSON object with these exact keys:
{
  "name": "John Doe",
  "email": "john@example.com",
  "phone": "+1-234-567-8900",
  "location": "New York, NY",
  "title": "Senior Software Engineer",
  "desired_role": "Tech Lead | Engineering Manager",
  "experience": "8+ years",
  "career_level": "senior",

  "skills": ["Python", "React", "AWS", "PostgreSQL"],
  "soft_skills": ["Leadership", "Communication", "Team Building"],
  "tools": ["Docker", "Kubernetes", "Git", "Jenkins"],
  "certifications": ["AWS Solutions Architect", "PMP"],
  "languages": [{"language": "English", "proficiency": "native"}, {"language": "Spanish", "proficiency": "conversational"}],

  "companies": [
    {"name": "TechCorp Inc", "title": "Senior Engineer", "duration": "2020-Present", "description": "Led team of 5 engineers"}
  ],
  "achievements": [
    "Increased system performance by 40%",
    "Led migration to microservices architecture"
  ],

  "education": [{"degree": "BS Computer Science", "institution": "MIT", "year": "2015"}],
  "summary": "8+ years building scalable systems..."
}

Guidelines:
- skills: programming languages, frameworks, libraries, technologies
- soft_skills: interpersonal, leadership, communication skills
- tools: software, platforms, CLI tools, devops tools
- certifications: formal certificates and training credentials
- languages: list of spoken languages with proficiency (native, fluent, conversational, basic)
- companies: work history with role, duration, and key responsibilities
- achievements: quantifiable accomplishments, awards, impact statements
- education: degrees, institutions, graduation years
- summary: 2-3 sentences professional overview

If a field cannot be determined, use: empty string ("") for text fields, empty array ([]) for list fields, empty array for objects list.""".strip()

JOB_MATCH_PROMPT = """Given this candidate resume:
{resume}

And this job listing:
Title: {title}
Company: {company}
Requirements: {requirements}

Score this job 0-100 based on:
- Skill match (40%)
- Experience level match (30%)  
- Education requirements (20%)
- Other factors (10%)

Return ONLY JSON:
{{"score": 85, "reason": "Good skill match in Python and React"}}""".strip()


def _get_llm_client():
    try:
        from openai import OpenAI

        return OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY", ""),
        )
    except Exception:
        return None


def _normalize_analysis(data: dict) -> dict:
    """Ensure analysis dict has all expected keys with safe defaults."""
    defaults = {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "title": "",
        "desired_role": "",
        "experience": "",
        "career_level": "",
        "skills": [],
        "soft_skills": [],
        "tools": [],
        "certifications": [],
        "languages": [],
        "companies": [],
        "achievements": [],
        "education": [],
        "summary": "",
    }
    # Fill missing keys
    for k, v in defaults.items():
        if k not in data:
            data[k] = v
    # Ensure list fields are actually lists
    list_fields = [
        "skills",
        "soft_skills",
        "tools",
        "certifications",
        "languages",
        "companies",
        "achievements",
        "education",
    ]
    for field in list_fields:
        if not isinstance(data.get(field), list):
            data[field] = []
    return data


def _analyze_image(image_b64: str) -> dict:
    client = _get_llm_client()
    if not client:
        return {
            "name": "",
            "email": "",
            "phone": "",
            "location": "",
            "title": "",
            "desired_role": "",
            "experience": "",
            "career_level": "",
            "skills": [],
            "soft_skills": [],
            "tools": [],
            "certifications": [],
            "languages": [],
            "companies": [],
            "achievements": [],
            "education": [],
            "summary": "Analysis pending - No API client available",
        }

    # EXCLUSIVELY use google/gemma-3-27b-it for vision-based resume parsing
    try:
        response = client.chat.completions.create(
            model=RESUME_MODEL,
            messages=[
                {"role": "system", "content": RESUME_ANALYZER_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": "Analyze this resume and extract the information in JSON format. Return ONLY the JSON.",
                        },
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"},
                        },
                    ],
                },
            ],
            max_tokens=2000,
            temperature=0.1,
        )
        content = response.choices[0].message.content
        if content:
            # Robust JSON extraction
            content = content.strip()
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()

            return _normalize_analysis(json.loads(content))
    except Exception as e:
        print(f"[resume] Gemma analysis failed: {e}")
        return {
            "name": "",
            "email": "",
            "phone": "",
            "location": "",
            "title": "",
            "desired_role": "",
            "experience": "Error",
            "career_level": "",
            "skills": [],
            "soft_skills": [],
            "tools": [],
            "certifications": [],
            "languages": [],
            "companies": [],
            "achievements": [],
            "education": [],
            "summary": f"Analysis failed: {str(e)}",
        }

    return {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "title": "",
        "desired_role": "",
        "experience": "",
        "career_level": "",
        "skills": [],
        "soft_skills": [],
        "tools": [],
        "certifications": [],
        "languages": [],
        "companies": [],
        "achievements": [],
        "education": [],
        "summary": "No content extracted",
    }


def _analyze_text(text: str) -> dict:
    client = _get_llm_client()
    if not client:
        return {
            "name": "",
            "email": "",
            "phone": "",
            "location": "",
            "title": "",
            "desired_role": "",
            "experience": "",
            "career_level": "",
            "skills": [],
            "soft_skills": [],
            "tools": [],
            "certifications": [],
            "languages": [],
            "companies": [],
            "achievements": [],
            "education": [],
            "summary": "Analysis pending",
        }

    try:
        response = client.chat.completions.create(
            model=RESUME_MODEL,
            messages=[
                {"role": "system", "content": RESUME_ANALYZER_PROMPT},
                {
                    "role": "user",
                    "content": f"Analyze this resume text:\n\n{text[:5000]}",
                },
            ],
            max_tokens=2000,
        )
        content = response.choices[0].message.content
        if content:
            content = content.strip().strip("```json").strip("```").strip()
            return json.loads(content)
    except Exception as e:
        print(f"[resume] AI text analysis failed: {e}")
    return {
        "name": "",
        "email": "",
        "phone": "",
        "location": "",
        "title": "",
        "desired_role": "",
        "experience": "",
        "career_level": "",
        "skills": [],
        "soft_skills": [],
        "tools": [],
        "certifications": [],
        "languages": [],
        "companies": [],
        "achievements": [],
        "education": [],
        "summary": "Analysis failed",
    }


@router.post("/upload")
async def upload_resume(file: UploadFile = File(...), user=Depends(current_user)):
    uid = int(user["sub"])

    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(
            400, f"Unsupported file type. Allowed: jpg, png, pdf, doc, docx"
        )

    ext = ALLOWED_TYPES[file.content_type]
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(400, "File too large. Max 10MB allowed")

    user_dir = RESUME_DIR / str(uid)
    user_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4()}.{ext}"
    file_path = user_dir / filename
    with open(file_path, "wb") as f:
        f.write(content)

    if ext in ("jpg", "png"):
        image_b64 = base64.b64encode(content).decode()
        analysis = _analyze_image(image_b64)
    else:
        text = ""
        if ext == "pdf":
            try:
                import PyPDF2
                import io

                reader = PyPDF2.PdfReader(io.BytesIO(content))
                text = "\n".join(p.extract_text() for p in reader.pages)
            except Exception:
                text = ""
        elif ext in ("doc", "docx"):
            try:
                import docx
                import io

                doc = docx.Document(io.BytesIO(content))
                text = "\n".join(p.text for p in doc.paragraphs)
            except Exception:
                text = ""

        if text:
            analysis = _analyze_text(text)
        else:
            analysis = {
                "skills": [],
                "experience": "",
                "education": [],
                "summary": "Could not extract text",
            }

    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()

        # Build common values
        values = {
            "filename": file.filename,
            "file_type": ext,
            "file_path": str(file_path),
            "extracted_text": text if ext not in ("jpg", "png") else None,
            "title": analysis.get("title", ""),
            "companies": json.dumps(analysis.get("companies", [])),
            "achievements": json.dumps(analysis.get("achievements", [])),
            "certifications": json.dumps(analysis.get("certifications", [])),
            "languages": json.dumps(analysis.get("languages", [])),
            "soft_skills": json.dumps(analysis.get("soft_skills", [])),
            "tools": json.dumps(analysis.get("tools", [])),
            "location": analysis.get("location", ""),
            "desired_role": analysis.get("desired_role", ""),
            "salary_range": analysis.get("salary_range", ""),
            "skills": json.dumps(analysis.get("skills", [])),
            "experience": analysis.get("experience", ""),
            "education": json.dumps(analysis.get("education", [])),
            "summary": analysis.get("summary", ""),
            "updated_at": None,
            # Store complete extracted data as backup
            "enhanced_data": json.dumps(analysis),
        }

        if existing:
            db.execute(
                """UPDATE resumes SET 
                    filename=?, file_type=?, file_path=?, extracted_text=?,
                    title=?, companies=?, achievements=?, certifications=?,
                    languages=?, soft_skills=?, tools=?, location=?,
                    desired_role=?, salary_range=?, skills=?, experience=?,
                    education=?, summary=?, enhanced_data=?, updated_at=datetime('now')
                WHERE user_id=?""",
                (
                    values["filename"],
                    values["file_type"],
                    values["file_path"],
                    values["extracted_text"],
                    values["title"],
                    values["companies"],
                    values["achievements"],
                    values["certifications"],
                    values["languages"],
                    values["soft_skills"],
                    values["tools"],
                    values["location"],
                    values["desired_role"],
                    values["salary_range"],
                    values["skills"],
                    values["experience"],
                    values["education"],
                    values["summary"],
                    values["enhanced_data"],
                    uid,
                ),
            )
        else:
            db.execute(
                """INSERT INTO resumes 
                    (user_id, filename, file_type, file_path, extracted_text,
                     title, companies, achievements, certifications, languages,
                     soft_skills, tools, location, desired_role, salary_range,
                     skills, experience, education, summary, enhanced_data)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    uid,
                    values["filename"],
                    values["file_type"],
                    values["file_path"],
                    values["extracted_text"],
                    values["title"],
                    values["companies"],
                    values["achievements"],
                    values["certifications"],
                    values["languages"],
                    values["soft_skills"],
                    values["tools"],
                    values["location"],
                    values["desired_role"],
                    values["salary_range"],
                    values["skills"],
                    values["experience"],
                    values["education"],
                    values["summary"],
                    values["enhanced_data"],
                ),
            )

    return {"status": "ok", "filename": file.filename, "analysis": analysis}


@router.get("/status")
def resume_status(user=Depends(current_user)):
    """Returns resume status for sidebar badge: {status: 'not_uploaded' | 'ready' | 'processing'}"""
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT skills, summary FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()

    if not row:
        return {"status": "not_uploaded"}

    # Check if resume is actually uploaded (has skills OR summary, not empty)
    skills = row["skills"] if row["skills"] else ""
    summary = row["summary"] if row["summary"] else ""

    if skills and summary and len(skills) > 0 and len(summary) > 0:
        return {"status": "ready"}

    if skills or summary:
        return {"status": "processing"}

    return {"status": "not_uploaded"}


@router.get("")
def get_resume(user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute("SELECT * FROM resumes WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return None
    r = dict(row)
    # Parse JSON list fields with safe defaults
    json_list_fields = [
        "skills",
        "education",
        "companies",
        "achievements",
        "certifications",
        "languages",
        "soft_skills",
        "tools",
    ]
    for field in json_list_fields:
        try:
            r[field] = json.loads(r.get(field, "[]") or "[]")
        except Exception:
            r[field] = []
    # Parse enhanced_data as dict if present
    try:
        r["enhanced_data"] = json.loads(r.get("enhanced_data", "{}") or "{}")
    except Exception:
        r["enhanced_data"] = {}
    return r


@router.delete("")
def delete_resume(user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute(
            "SELECT file_path FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()
        if row:
            path = Path(row["file_path"])
            if path.exists():
                path.unlink()
        db.execute("DELETE FROM resumes WHERE user_id=?", (uid,))
    return {"status": "deleted"}


@router.get("/match/{job_id}")
def match_job(job_id: int, user=Depends(current_user)):
    uid = int(user["sub"])

    with get_db() as db:
        resume_row = db.execute(
            "SELECT * FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()
        job_row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    if not resume_row or not job_row:
        raise HTTPException(404, "Resume or job not found")

    # Convert sqlite3.Row to dict
    resume = dict(resume_row) if resume_row else {}
    job = dict(job_row) if job_row else {}

    resume_skills = json.loads(resume.get("skills", "[]"))
    resume_exp = resume.get("experience", "")

    job_title = job.get("title", "")
    job_company = job.get("company", "")
    job_exp = job.get("experience", "")

    prompt = f"""Resume:
Skills: {", ".join(resume_skills)}
Experience: {resume_exp}

Job:
Title: {job_title}
Company: {job_company}
Experience: {job_exp}

Score 0-100. Return ONLY JSON with 'score' and 'reason' keys."""

    try:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY", ""),
        )
        response = client.chat.completions.create(
            model=RESUME_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You match resumes to jobs. Return JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
        )
        content = response.choices[0].message.content.strip()
        content = content.strip().strip("```json").strip("```").strip()
        return _normalize_analysis(json.loads(content))
    except Exception as e:
        print(f"[action_plans] AI generation failed: {e}")
        # Fallback basic action plans
        return {
            "python": "Start with Python basics - complete online tutorial in 2 weeks",
            "javascript": "Learn JS fundamentals - freeCodeCamp is a good starting point",
            "react": "Build a portfolio project to learn React basics",
            "aws": "Use AWS Free Tier for hands-on cloud experience",
            "sql": "Practice SQL with LeetCode or W3Schools exercises",
        }


def _build_career_strategy(ranked_jobs, summary, insights, jobs_data, resume_skills):
    """
    Build 4-card Career Sprint dashboard from analyzed job results.
    All data is derived from job scores, LLM insights, and market aggregation.
    """
    import re
    from collections import Counter

    # ── Card 1: Priority Jobs (top 3) ──────────────────────────────────────
    priority_jobs = []
    for job in ranked_jobs[:3]:
        missing = job.get("missing_skills", [])
        tip = (
            f"Quick prep: learn {missing[0]} to strengthen your application."
            if missing
            else "You meet all core requirements — apply now!"
        )
        priority_jobs.append(
            {
                "id": job["id"],
                "title": job["title"],
                "company": job["company"],
                "location": job.get("location", ""),
                "match_score": job["match_score"],
                "match_reason": job.get("match_reason", ""),
                "prep_tip": tip,
                "missing_skills": missing,
            }
        )

    # ── Card 2: Learning Sprint ────────────────────────────────────────────
    # Aggregate missing skills across all ranked jobs
    missing_counter = Counter()
    for job in ranked_jobs:
        for skill in job.get("missing_skills", []):
            missing_counter[skill] += 1

    top_missing = missing_counter.most_common(5)

    # Rough time estimates per skill (in weeks)
    TIME_MAP = {
        "docker": 2,
        "kubernetes": 4,
        "k8s": 4,
        "aws": 3,
        "azure": 3,
        "gcp": 3,
        "react": 2,
        "angular": 2,
        "vue": 2,
        "node": 2,
        "javascript": 1,
        "typescript": 1,
        "python": 1,
        "java": 2,
        "go": 2,
        "rust": 3,
        "sql": 1,
        "postgresql": 1,
        "mongodb": 1,
        "redis": 1,
        "ci/cd": 2,
        "jenkins": 2,
        "gitlab": 2,
        "github actions": 1,
        "linux": 1,
        "nginx": 1,
        "docker-compose": 2,
        "machine learning": 4,
        "ai": 4,
        "deep learning": 5,
        "agile": 1,
        "scrum": 1,
    }
    HOURS_PER_WEEK = 6

    learning_skills = []
    for idx, (skill, count) in enumerate(top_missing):
        skill_lower = skill.lower()
        weeks = TIME_MAP.get(skill_lower, 2)
        learning_skills.append(
            {
                "skill": skill,
                "priority": idx + 1,
                "estimated_weeks": weeks,
                "hours_per_week": HOURS_PER_WEEK,
                "jobs_unlocked": count,
                "why": f"Required by {count} jobs you're missing",
            }
        )

    learning_sprint = {
        "total_weeks": sum(s["estimated_weeks"] for s in learning_skills),
        "skills": learning_skills,
    }

    # ── Card 3: Market Hotspots ───────────────────────────────────────────
    # Parse salary strings
    salary_numbers = []
    for j in jobs_data:
        sal = (j.get("salary") or "").strip()
        if sal and "negotiat" not in sal.lower() and "competitive" not in sal.lower():
            nums = re.findall(r"\d+", sal)
            salary_numbers.extend([int(n) for n in nums if int(n) > 1000])
    if salary_numbers:
        min_sal = min(salary_numbers)
        max_sal = max(salary_numbers)
        avg_sal = int(sum(salary_numbers) / len(salary_numbers))
    else:
        min_sal = max_sal = avg_sal = 0

    # Locations
    loc_counter = Counter()
    for j in jobs_data:
        loc = (j.get("location") or "").strip()
        if loc and loc.lower() not in ("not specified", "n/a", ""):
            loc_counter[loc] += 1
    top_locations = [
        {"location": loc, "count": c, "pct": round(c * 100.0 / len(jobs_data), 1)}
        for loc, c in loc_counter.most_common(5)
    ]

    # Job types
    type_counter = Counter()
    for j in jobs_data:
        jt = (j.get("job_type") or "").strip()
        if jt:
            type_counter[jt] += 1
    total_jt = sum(type_counter.values()) or 1
    job_type_mix = [
        {"type": t, "count": c, "pct": round(c * 100.0 / total_jt, 1)}
        for t, c in type_counter.most_common(4)
    ]

    # Industry (use industry field; fallback to company)
    ind_counter = Counter()
    for j in jobs_data:
        ind = (j.get("industry") or "").strip()
        if not ind:
            ind = (j.get("company") or "").strip()
        if ind:
            ind_counter[ind] += 1
    top_industries = [
        {"industry": ind, "count": c, "pct": round(c * 100.0 / len(jobs_data), 1)}
        for ind, c in ind_counter.most_common(4)
    ]

    # Remote vs Onsite heuristic
    remote_count = 0
    for j in jobs_data:
        combined = (j.get("job_type", "") + " " + j.get("location", "")).lower()
        if "remote" in combined or "work from home" in combined:
            remote_count += 1
    remote_onsite = {"remote": remote_count, "onsite": len(jobs_data) - remote_count}

    market_hotspots = {
        "salary_range": {
            "min": min_sal,
            "max": max_sal,
            "avg": avg_sal,
            "currency": "BDT",
        },
        "top_locations": top_locations,
        "job_type_mix": job_type_mix,
        "industry_demand": top_industries,
        "remote_onsite": remote_onsite,
    }

    # ── Card 4: Competitive Edge ───────────────────────────────────────────
    avg_match = summary.get("avg_match", 0)
    if avg_match >= 85:
        tier, tier_pct = "Top Performer", 99
    elif avg_match >= 75:
        tier, tier_pct = "Strong", 85
    elif avg_match >= 65:
        tier, tier_pct = "Competitive", 70
    else:
        tier, tier_pct = "Developing", 35

    superpower = (insights.get("top_matching_skills") or [None])[0] or "N/A"
    key_gap = (insights.get("skills_to_learn") or [None])[0] or "N/A"
    ready_jobs_count = summary.get("high_matches", 0) or 0

    competitive_edge = {
        "tier": tier,
        "tier_percentile": tier_pct,
        "superpower": superpower,
        "key_gap": key_gap,
        "ready_jobs_count": ready_jobs_count,
        "next_step": f"Apply to {ready_jobs_count} jobs this week"
        if ready_jobs_count
        else "Build skills first",
    }

    return {
        "priority_jobs": priority_jobs,
        "learning_sprint": learning_sprint,
        "market_hotspots": market_hotspots,
        "competitive_edge": competitive_edge,
        "summary": {
            "total_jobs_analyzed": summary.get("total", len(ranked_jobs)),
            "avg_match": avg_match,
        },
    }


def _generate_action_plans(resume_skills, top_skills, missing):
    """Generate AI action plans for missing skills."""
    import traceback
    import logging

    logger = logging.getLogger(__name__)

    if not missing:
        return {}

    prompt = f"""Resume skills: {", ".join(resume_skills)}
Missing skills: {", ".join(missing)}
Top job skills: {", ".join(top_skills[:10]) if top_skills else ""}

Generate action plans for each missing skill. Return ONLY a JSON object with skill names as keys and short action plan strings as values. Example format: {{"python": "Learn Python basics - 2 week tutorial", "aws": "Get AWS certified"}}"""

    api_key = os.environ.get("NEBIUS_API_KEY", "")
    logger.info(f"[ACTION_PLANS] API key present: {bool(api_key)}")
    logger.info(f"[ACTION_PLANS] Resume skills: {resume_skills}")
    logger.info(f"[ACTION_PLANS] Missing skills: {missing}")
    logger.info(f"[ACTION_PLANS] Top skills: {top_skills[:10]}")

    try:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=api_key,
        )
        logger.info(f"[ACTION_PLANS] Calling AI model: {RESUME_MODEL}")

        response = client.chat.completions.create(
            model=RESUME_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You generate career action plans. Return JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=500,
            temperature=0.7,
        )

        content = response.choices[0].message.content.strip()
        logger.info(f"[ACTION_PLANS] Raw response: {content[:200]}...")
        content = content.strip().strip("```json").strip("```").strip()
        result = json.loads(content)
        logger.info(f"[ACTION_PLANS] Parsed result: {result}")
        return result
    except Exception as e:
        logger.error(f"[_generate_action_plans] AI call failed: {e}")
        logger.error(
            f"[_generate_action_plans] Full traceback: {traceback.format_exc()}"
        )
        # Fallback basic action plans
        return {
            "python": "Start with Python basics - complete online tutorial in 2 weeks",
            "javascript": "Learn JS fundamentals - freeCodeCamp is a good starting point",
            "react": "Build a portfolio project to learn React basics",
            "aws": "Use AWS Free Tier for hands-on cloud experience",
            "sql": "Practice SQL with LeetCode or W3Schools exercises",
            "docker": "Learn Docker basics with free container tutorials",
            "kubernetes": "Start with Minikube and local Kubernetes exercises",
            "typescript": "Convert your JS projects to TS for practice",
            "java": "Complete Java fundamentals course on Codecademy",
            "go": "Build CLI tools in Go for practice",
        }


def _generate_career_insights(
    resume_profile, top_skills, missing, market_skills, saved_rows_data=None
):
    """Generate AI-powered career insights using full resume data and job data."""
    import traceback

    # Build detailed prompt with all resume info
    skills_str = ", ".join(resume_profile.get("skills", []))
    soft_skills_str = ", ".join(resume_profile.get("soft_skills", []))
    tools_str = ", ".join(resume_profile.get("tools", []))
    certs_str = ", ".join(resume_profile.get("certifications", []))
    companies_str = json.dumps(resume_profile.get("companies", []))
    achievements_str = ", ".join(resume_profile.get("achievements", []))
    education_str = json.dumps(resume_profile.get("education", []))
    experience = resume_profile.get("experience", "")
    career_level = resume_profile.get("career_level", "")
    summary = resume_profile.get("summary", "")

    # Get additional job matching data for more personalized insights
    saved_rows = saved_rows_data if saved_rows_data else []
    job_titles_in_saved = (
        [j.get("title", "") for j in saved_rows[:10]] if saved_rows else []
    )
    job_companies = (
        [j.get("company", "") for j in saved_rows[:10]] if saved_rows else []
    )

    prompt = f"""You are a career coach specializing in the BANGLADESH job market (Dhaka, Bangladesh). All salary figures must be in BDT (Bangladeshi Taka). Generate personalized career insights based on THE USER'S ACTUAL DATA.

RESUME DATA (from uploaded resume):
- Current Title/Role: {resume_profile.get("name", "N/A")}
- Experience: {experience} ({career_level} level)
- Technical Skills: {skills_str}
- Soft Skills: {soft_skills_str}
- Tools & Platforms: {tools_str}
- Key Achievements: {achievements_str}

JOBS DATA (user has saved/searched {len(saved_rows) if saved_rows else 0} jobs):
- Jobs Target These Titles: {", ".join(set(job_titles_in_saved)) if job_titles_in_saved else "N/A"}
- Companies: {", ".join(set(job_companies)) if job_companies else "N/A"}
- Skills in These Jobs: {", ".join(top_skills[:10]) if top_skills else "N/A"}

SKILL GAP ANALYSIS:
- Your Skills Match These: {", ".join([s for s in top_skills if s.lower() in [rs.lower() for rs in resume_profile.get("skills", [])]]) if resume_profile.get("skills", []) else "None"}
- Missing Skills (jobs need this, you don't have): {", ".join(missing[:5]) if missing else "None"}
- Market Hot Skills: {", ".join(market_skills) if market_skills else "N/A"}

IMPORTANT CONTEXT:
- Location: Dhaka, Bangladesh
- Currency: BDT (Bangladeshi Taka) - use ৳ symbol
- Market: Local IT companies, outsourcing firms (BPO/KPO), startups, and international remote roles
- Entry-level: ৳30,000 - ৳80,000/month
- Mid-level: ৳60,000 - ৳150,000/month
- Senior: ৳100,000 - ৳300,000+/month

Based on the user's ACTUAL resume skills AND the jobs they've saved, generate specific insights.
Use the SKILL GAP ANALYSIS to recommend which skills to learn based on actual job demand.
Recommend roles based on job titles they're actually applying to.

Generate a JSON response with these fields:
{{
  "recommended_role": "Best matching job title based on their saved jobs and skills",
  "strengths": ["3-4 strengths based on their ACTUAL resume skills that match job requirements"],
  "market_value": "1-2 sentences on where they stand in Bangladesh market based on actual match data",
  "growth_opportunities": ["top 3 skills they should learn based on job gaps"],
  "salary_insights": "salary range in BDT based on their experience level",
  "next_steps": ["specific actionable steps: jobs to apply to, skills to learn, companies to target"],
  "competitive_advantages": ["what makes them stand out based on their resume vs job needs"],
  "areas_for_improvement": ["specific skill gaps to close based on saved jobs"]
}}"""

    api_key = os.environ.get("NEBIUS_API_KEY", "")

    try:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=api_key,
        )

        response = client.chat.completions.create(
            model=RESUME_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert career coach. Generate detailed, personalized career insights in JSON format.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000,
            temperature=0.7,
        )

        content = response.choices[0].message.content.strip()
        content = content.strip().strip("```json").strip("```").strip()
        result = json.loads(content)

        # Ensure all required keys exist
        default_insights = {
            "recommended_role": "Based on your skills",
            "strengths": resume_profile.get("skills", [])[:5],
            "market_value": "Your skills are in demand. positions you well.",
            "growth_opportunities": missing[:3] if missing else [],
            "salary_insights": "Market rates vary by location and experience.",
            "next_steps": [
                "Continue applying to matching jobs",
                "Upskill in missing areas",
            ],
            "competitive_advantages": resume_profile.get("skills", [])[:3],
            "areas_for_improvement": missing[:3] if missing else [],
        }

        # Merge with defaults
        for key in default_insights:
            if key not in result:
                result[key] = default_insights[key]

        return result

    except Exception as e:
        print(f"[_generate_career_insights] AI call failed: {e}")
        # Fallback insights using resume data - Bangladesh context
        return {
            "recommended_role": resume_profile.get("name", "Based on your skills"),
            "strengths": resume_profile.get("skills", [])[:5],
            "market_value": f"Your {experience} of experience and technical skills position you well in the Bangladesh IT market.",
            "growth_opportunities": missing[:3]
            if missing
            else ["Cloud technologies", "System design"],
            "salary_insights": "Entry-level: ৳30,000-60,000/month | Mid-level: ৳60,000-120,000/month (BDT)",
            "next_steps": [
                "Apply to local IT firms, BPO/KPO companies, and startups in Dhaka",
                "Consider remote roles for higher pay",
                "Build portfolio projects to showcase skills",
            ],
            "competitive_advantages": resume_profile.get("achievements", [])[:3]
            if resume_profile.get("achievements")
            else resume_profile.get("skills", [])[:3],
            "areas_for_improvement": missing[:3] if missing else [],
        }


@router.get("/insights")
def get_insights(
    search_id: int | None = None,
    saved: bool = True,
    user=Depends(current_user),
):
    from database import get_column

    uid = int(user["sub"])

    with get_db() as db:
        resume_row = db.execute(
            "SELECT * FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()

        # Get only SAVED jobs for personalized insights (or all if saved=False)
        saved_filter = "AND saved = 1" if saved else ""
        if search_id:
            saved_rows = db.execute(
                f"SELECT * FROM jobs WHERE user_id=? AND search_id=? AND is_deleted=0 {saved_filter} ORDER BY id DESC LIMIT 100",
                (uid, search_id),
            ).fetchall()
        else:
            saved_rows = db.execute(
                f"SELECT * FROM jobs WHERE user_id=? AND is_deleted=0 {saved_filter} ORDER BY id DESC LIMIT 100",
                (uid,),
            ).fetchall()

    if not resume_row:
        return {"insights": [], "summary": {"error": "No resume found"}}

    resume = dict(resume_row) if resume_row else {}
    resume_skills = json.loads(resume.get("skills", []))

    all_job_skills = []
    for row in saved_rows:
        job = dict(row) if row else {}
        job_skills = job.get("skills", "")
        if job_skills:
            all_job_skills.extend([s.strip() for s in job_skills.split(",")])
        else:
            title = job.get("title", "").lower()
            common = [
                "react",
                "node",
                "python",
                "java",
                "javascript",
                "sql",
                "aws",
                "docker",
                "kubernetes",
                "typescript",
                "angular",
                "vue",
                "django",
                "flask",
                "spring",
                "php",
                "ruby",
                "go",
                "rust",
                "c#",
                ".net",
            ]
            for skill in common:
                if skill in title:
                    all_job_skills.append(skill)

    from collections import Counter

    skill_counts = Counter(all_job_skills)
    top_skills = [s for s, _ in skill_counts.most_common(10)]

    missing = [
        s for s in top_skills if s.lower() not in [rs.lower() for rs in resume_skills]
    ]

    top_job_skills = []
    for row in saved_rows:
        job = dict(row) if row else {}
        job_skills = job.get("skills", "")
        if job_skills:
            top_job_skills.extend([s.strip() for s in job_skills.split(",")])

    job_skill_counts = Counter(top_job_skills)
    market_skills = [s for s, _ in job_skill_counts.most_common(5)]

    insights = []
    if top_skills:
        insights.append(f"Most jobs require: {', '.join(top_skills[:5])}")
    if missing:
        insights.append(f"You're missing: {', '.join(missing[:3])}")

    # Calculate avg_match percentage
    total_job_skills = len(top_skills) if top_skills else 1
    matched_count = len(
        [s for s in top_skills if s.lower() in [rs.lower() for rs in resume_skills]]
    )
    avg_match = (
        round((matched_count / total_job_skills) * 100) if total_job_skills > 0 else 0
    )

    skill_gaps = []
    # Generate action plans for skill gaps using AI prompt
    action_plans = (
        _generate_action_plans(resume_skills, top_skills, missing[:3])
        if missing
        else {}
    )

    for s in top_skills[:8]:
        is_in_resume = s.lower() in [rs.lower() for rs in resume_skills]
        # Get personalized action plan for missing skills
        plan = action_plans.get(s.lower(), "") if not is_in_resume else ""

        skill_gaps.append(
            {
                "skill": s,
                "required": s,
                "have": s if is_in_resume else "",
                "status": "matched" if is_in_resume else "missing",
                "action_plan": plan,
            }
        )

    # Get full resume data from enhanced_data field
    enhanced_data = {}
    try:
        enhanced_data = (
            json.loads(resume.get("enhanced_data", "{}"))
            if resume.get("enhanced_data")
            else {}
        )
    except:
        pass

    # Build comprehensive resume profile from extracted data
    resume_profile = {
        "name": resume.get("title", "") or enhanced_data.get("name", ""),
        "email": enhanced_data.get("email", ""),
        "phone": enhanced_data.get("phone", ""),
        "location": enhanced_data.get("location", ""),
        "experience": resume.get("experience", "")
        or enhanced_data.get("experience", ""),
        "career_level": enhanced_data.get("career_level", ""),
        "summary": resume.get("summary", "") or enhanced_data.get("summary", ""),
        "skills": resume_skills,
        "soft_skills": json.loads(resume.get("soft_skills", "[]"))
        if resume.get("soft_skills")
        else enhanced_data.get("soft_skills", []),
        "tools": json.loads(resume.get("tools", "[]"))
        if resume.get("tools")
        else enhanced_data.get("tools", []),
        "certifications": json.loads(resume.get("certifications", "[]"))
        if resume.get("certifications")
        else enhanced_data.get("certifications", []),
        "languages": json.loads(resume.get("languages", "[]"))
        if resume.get("languages")
        else enhanced_data.get("languages", []),
        "companies": json.loads(resume.get("companies", "[]"))
        if resume.get("companies")
        else enhanced_data.get("companies", []),
        "achievements": json.loads(resume.get("achievements", "[]"))
        if resume.get("achievements")
        else enhanced_data.get("achievements", []),
        "education": json.loads(resume.get("education", "[]"))
        if resume.get("education")
        else enhanced_data.get("education", []),
    }

    # Generate AI-powered career insights using the full resume data and job data
    saved_rows_for_ai = [dict(row) for row in saved_rows] if saved_rows else []
    career_insights = _generate_career_insights(
        resume_profile, top_skills, missing, market_skills, saved_rows_for_ai
    )

    return {
        "insights": insights,
        "resume_profile": resume_profile,
        "career_insights": career_insights,
        "summary": {
            "best_role": career_insights.get(
                "recommended_role", "Based on your skills"
            ),
            "avg_match": f"{avg_match}%",
            "top_missing": missing[:5],
            "jobs_found": len(saved_rows),
            "experience_years": resume_profile.get("experience", ""),
            "career_level": resume_profile.get("career_level", ""),
        },
        "skill_gaps": skill_gaps,
        "recommendation": f"Focus on learning {', '.join(missing[:3]) if missing else 'the key skills listed above'} to improve your job match rate. Consider taking online courses or working on projects that use these technologies."
        if missing
        else "Great job! Your skills are well-aligned with market demands. Keep building on your strengths.",
        "market_insights": {
            "top_demanded": market_skills,
            "total_saved": len(saved_rows),
        },
    }


# ── NEW: LLM-Powered Job Analysis Endpoint ───────────────────────────────────────


@router.get("/analyze-jobs-stream")
def analyze_jobs_stream(
    limit: int = 50,
    search_id: Optional[int] = None,
    session_id: Optional[str] = None,
    user=Depends(current_user),
):
    """
    Stream job analysis results as they are computed.
    Uses Server-Sent Events (SSE) to send each job result immediately when ready.
    """
    import asyncio
    from fastapi.responses import StreamingResponse

    uid = int(user["sub"])

    async def event_generator():
        from database import get_db

        with get_db() as db:
            # Get user's resume
            resume_row = db.execute(
                "SELECT * FROM resumes WHERE user_id=?", (uid,)
            ).fetchone()

            if not resume_row:
                yield 'data: {"error": "No resume found"}\n\n'
                return

            resume = dict(resume_row)
            resume_skills = json.loads(resume.get("skills", "[]"))
            resume_exp = resume.get("experience", "")
            resume_summary = resume.get("summary", "")

            # Get all jobs
            if session_id:
                jobs_rows = db.execute(
                    "SELECT j.* FROM jobs j "
                    "JOIN searches s ON j.search_id = s.id "
                    "WHERE s.session_id=? AND j.user_id=? AND j.is_deleted=0 ORDER BY j.id DESC LIMIT ?",
                    (session_id, uid, limit),
                ).fetchall()
            elif search_id:
                jobs_rows = db.execute(
                    "SELECT * FROM jobs WHERE user_id=? AND search_id=? AND is_deleted=0 ORDER BY id DESC LIMIT ?",
                    (uid, search_id, limit),
                ).fetchall()
            else:
                jobs_rows = db.execute(
                    "SELECT * FROM jobs WHERE user_id=? AND is_deleted=0 ORDER BY id DESC LIMIT ?",
                    (uid, limit),
                ).fetchall()

            if not jobs_rows:
                yield 'data: {"error": "No jobs found"}\n\n'
                return

        # Build jobs data
        jobs_data = []
        for job_row in jobs_rows:
            job = dict(job_row)
            jobs_data.append(
                {
                    "id": job["id"],
                    "title": job.get("title", ""),
                    "company": job.get("company", ""),
                    "skills": job.get("skills", ""),
                    "experience": job.get("experience", ""),
                    "location": job.get("location", ""),
                    "url": job.get("url", ""),
                }
            )

        # Send initial count
        yield f"data: {json.dumps({'type': 'start', 'total': len(jobs_data)})}\n\n"

        # Send "analyzing" status
        yield f"data: {json.dumps({'type': 'status', 'message': 'Starting AI analysis...'})}\n\n"

        # Process jobs in BATCHES for faster analysis (multiple jobs per LLM call)
        from openai import OpenAI
        import asyncio

        client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY", ""),
        )

        # Batch size: how many jobs to analyze in one LLM call (more = faster, but larger prompt)
        BATCH_SIZE = 5
        analyzed = []

        # Process jobs in batches
        for batch_idx in range(0, len(jobs_data), BATCH_SIZE):
            batch = jobs_data[batch_idx : batch_idx + BATCH_SIZE]
            batch_start_idx = batch_idx

            try:
                # Create a batch prompt analyzing multiple jobs at once
                jobs_description = "\n".join(
                    [
                        f"{i + 1}. Job: {j['title']} at {j['company']}, Skills: {j.get('skills', 'Not specified')}, Experience: {j.get('experience', 'Not specified')}"
                        for i, j in enumerate(batch)
                    ]
                )

                prompt = f"""Analyze these jobs for a candidate with:
- Skills: {", ".join(resume_skills)}
- Experience: {resume_exp}

Jobs to analyze:
{jobs_description}

Return a JSON array with one entry per job. Each entry should have: score (0-100), match_reason (string), missing_skills (array), strengths (array).
Format: [{{"score": 0, "match_reason": "...", "missing_skills": [...], "strengths": [...]}}, ...]"""

                response = client.chat.completions.create(
                    model=RESUME_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a job matching expert. Return ONLY valid JSON array.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=2000,  # Increased for batch
                    temperature=0.3,
                )

                content = response.choices[0].message.content.strip()
                content = content.strip("```json").strip("```").strip()

                # Parse batch results
                results = json.loads(content)

                # Handle case where single object returned instead of array
                if isinstance(results, dict) and "score" in results:
                    results = [results]

            except Exception as e:
                print(f"[stream] Batch analysis failed: {e}")
                # Fallback: simple matching for each job in batch
                results = []
                for job in batch:
                    job_skills = [
                        s.strip().lower()
                        for s in job.get("skills", "").split(",")
                        if s.strip()
                    ]
                    matched = [s for s in resume_skills if s.lower() in job_skills]
                    missing = [
                        s
                        for s in job_skills
                        if s.lower() not in [rs.lower() for rs in resume_skills]
                    ]
                    score = (
                        min(100, int((len(matched) / max(len(job_skills), 1)) * 100))
                        if job_skills
                        else 50
                    )
                    results.append(
                        {
                            "score": score,
                            "match_reason": f"Matched on {len(matched)} skills"
                            + (f", missing {len(missing)}" if missing else ""),
                            "missing_skills": missing[:5],
                            "strengths": matched,
                        }
                    )

            # Process results for each job in batch
            for i, (job, result) in enumerate(zip(batch, results)):
                if isinstance(result, dict):
                    analysis = {
                        "score": result.get("score", 50),
                        "reason": result.get("match_reason", ""),
                        "missing": result.get("missing_skills", []),
                        "strengths": result.get("strengths", []),
                    }
                else:
                    # Fallback for invalid result
                    analysis = {
                        "score": 50,
                        "reason": "Analysis unavailable",
                        "missing": [],
                        "strengths": [],
                    }

                # Get saved status
                with get_db() as db:
                    saved_row = db.execute(
                        "SELECT saved FROM jobs WHERE id=? AND user_id=?",
                        (job["id"], uid),
                    ).fetchone()
                    saved = saved_row["saved"] if saved_row else 0

                job_result = {
                    "id": job["id"],
                    "title": job["title"],
                    "company": job["company"],
                    "location": job["location"],
                    "url": job.get("url", ""),
                    "skills": job["skills"],
                    "experience": job["experience"],
                    "match_score": analysis["score"],
                    "match_reason": analysis["reason"],
                    "missing_skills": analysis["missing"],
                    "strengths": analysis["strengths"],
                    "saved": saved,
                }

                analyzed.append(job_result)

                # Send each job result as it completes
                yield f"data: {json.dumps({'type': 'job', 'job': job_result, 'index': batch_start_idx + i, 'total': len(jobs_data)})}\n\n"

        # Sort by score and send final results
        analyzed.sort(key=lambda x: x["match_score"], reverse=True)

        scores = [j["match_score"] for j in analyzed]
        avg_score = int(sum(scores) / len(scores)) if scores else 0

        summary = {
            "total": len(analyzed),
            "avg_match": avg_score,
            "high_matches": len([s for s in scores if s >= 70]),
            "medium_matches": len([s for s in scores if 60 <= s < 80]),
            "low_matches": len([s for s in scores if s < 60]),
        }

        yield f"data: {json.dumps({'type': 'done', 'jobs': analyzed, 'summary': summary})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/analyze-jobs")
def analyze_all_jobs(
    limit: int = 50,
    search_id: Optional[int] = None,
    session_id: Optional[str] = None,
    saved: bool = False,
    user=Depends(current_user),
):
    """
    Analyze ALL jobs using LLM for intelligent matching.
    Returns ranked jobs with AI scores, skill gaps, and insights.
    Accepts either search_id (integer) or session_id (UUID string).
    """
    uid = int(user["sub"])

    with get_db() as db:
        # Get user's resume
        resume_row = db.execute(
            "SELECT * FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()

        if not resume_row:
            return {
                "jobs": [],
                "summary": {"error": "No resume found"},
                "insights": {},
                "career_strategy": {},
            }

        resume = dict(resume_row)
        resume_skills = json.loads(resume.get("skills", "[]"))
        resume_exp = resume.get("experience", "")
        resume_summary = resume.get("summary", "")

        # Get all jobs (not just saved ones)
        saved_filter = "AND saved = 1" if saved else ""
        if session_id:
            # Use session_id (UUID) - join with searches table
            jobs_rows = db.execute(
                f"SELECT j.* FROM jobs j JOIN searches s ON j.search_id = s.id WHERE s.session_id=? AND j.user_id=? AND j.is_deleted=0 {saved_filter} ORDER BY j.id DESC LIMIT ?",
                (session_id, uid, limit),
            ).fetchall()
        elif search_id:
            # Use search_id (integer)
            jobs_rows = db.execute(
                f"SELECT * FROM jobs WHERE user_id=? AND search_id=? AND is_deleted=0 {saved_filter} ORDER BY id DESC LIMIT ?",
                (uid, search_id, limit),
            ).fetchall()
        else:
            # Get all jobs
            jobs_rows = db.execute(
                f"SELECT * FROM jobs WHERE user_id=? AND is_deleted=0 {saved_filter} ORDER BY id DESC LIMIT ?",
                (uid, limit),
            ).fetchall()

        if not jobs_rows:
            return {
                "jobs": [],
                "summary": {"total": 0},
                "insights": {},
                "career_strategy": {},
            }

    # Build prompt for batch analysis
    jobs_data = []
    for job_row in jobs_rows:
        job = dict(job_row)
        jobs_data.append(
            {
                "id": job["id"],
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "skills": job.get("skills", "") or "",
                "experience": job.get("experience", "") or "",
                "location": job.get("location", "") or "",
                "salary": job.get("salary", "") or "",
                "job_type": job.get("job_type", "") or "",
                "industry": job.get("industry", "") or "",
            }
        )

    # Format jobs for LLM
    jobs_text = "\n\n".join(
        [
            f"Job {i + 1}: {j['title']} at {j['company']}. Skills: {j['skills']}. Experience: {j['experience']}. Location: {j['location']}"
            for i, j in enumerate(jobs_data)
        ]
    )

    prompt = f"""You are an AI job matching expert. Analyze these jobs for a candidate and provide scores.

CANDIDATE PROFILE:
- Skills: {", ".join(resume_skills)}
- Experience: {resume_exp}
- Summary: {resume_summary}

JOBS TO ANALYZE:
{jobs_text}

For each job, return a JSON array with this exact structure (no other text):
{{
  "analysis": [
    {{"job_id": 1, "score": 85, "match_reason": "Strong match in Python and React", "missing_skills": ["AWS"], "strengths": ["Python", "React"]}},
    ...
  ],
  "insights": {{
    "top_matching_skills": ["Python", "React"],
    "skills_to_learn": ["AWS", "Docker"],
    "market_trends": "Cloud and DevOps skills are in high demand"
  }}
}}

Score based on: skill match (50%), experience level (30%), overall fit (20%).
Provide specific missing skills and strengths for each job."""

    try:
        from openai import OpenAI

        client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY", ""),
        )

        response = client.chat.completions.create(
            model=RESUME_MODEL,
            messages=[
                {
                    "role": "system",
                    "content": "You are an expert job matching AI. Always return valid JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=4000,
            temperature=0.3,
        )

        content = response.choices[0].message.content.strip()
        # Clean up markdown if present
        content = content.strip("```json").strip("```").strip()

        result = json.loads(content)

        # Map analysis back to jobs
        analysis_map = {a["job_id"]: a for a in result.get("analysis", [])}
        insights = result.get("insights", {})

        ranked_jobs = []
        for job in jobs_data:
            analysis = analysis_map.get(
                job["id"],
                {
                    "score": 50,
                    "match_reason": "Analyzing...",
                    "missing_skills": [],
                    "strengths": [],
                },
            )

            # Get saved status
            with get_db() as db:
                saved_row = db.execute(
                    "SELECT saved FROM jobs WHERE id=? AND user_id=?", (job["id"], uid)
                ).fetchone()
                saved = saved_row["saved"] if saved_row else 0

            ranked_jobs.append(
                {
                    "id": job["id"],
                    "title": job["title"],
                    "company": job["company"],
                    "location": job["location"],
                    "skills": job["skills"],
                    "experience": job["experience"],
                    "match_score": analysis.get("score", 50),
                    "match_reason": analysis.get("match_reason", ""),
                    "missing_skills": analysis.get("missing_skills", []),
                    "strengths": analysis.get("strengths", []),
                    "saved": saved,
                }
            )

        # Sort by score
        ranked_jobs.sort(key=lambda x: x["match_score"], reverse=True)

        # Calculate summary
        scores = [j["match_score"] for j in ranked_jobs]
        avg_score = int(sum(scores) / len(scores)) if scores else 0
        summary = {
            "total": len(ranked_jobs),
            "avg_match": avg_score,
            "high_matches": len([s for s in scores if s >= 70]),
            "medium_matches": len([s for s in scores if 60 <= s < 80]),
            "low_matches": len([s for s in scores if s < 60]),
        }

        # Compute career strategy
        career_strategy = _build_career_strategy(
            ranked_jobs, summary, insights, jobs_data, resume_skills
        )

        return {
            "jobs": ranked_jobs[:limit],
            "summary": summary,
            "insights": insights,
            "career_strategy": career_strategy,
        }

    except Exception as e:
        print(f"[analyze-jobs] LLM error: {e}")

        # Fallback to simple matching
        ranked_jobs = []
        for job in jobs_data:
            job_skills = [
                s.strip().lower() for s in job.get("skills", "").split(",") if s.strip()
            ]
            matched = [s for s in resume_skills if s.lower() in job_skills]
            missing = [
                s
                for s in job_skills
                if s.lower() not in [rs.lower() for rs in resume_skills]
            ]
            score = (
                min(100, int((len(matched) / max(len(job_skills), 1)) * 100))
                if job_skills
                else 50
            )

            ranked_jobs.append(
                {
                    "id": job["id"],
                    "title": job["title"],
                    "company": job["company"],
                    "location": job["location"],
                    "skills": job["skills"],
                    "match_score": score,
                    "match_reason": f"Matched on {len(matched)} skills"
                    + (f", missing {len(missing)}" if missing else ""),
                    "missing_skills": missing[:5],
                    "strengths": matched,
                    "saved": 0,
                }
            )

        ranked_jobs.sort(key=lambda x: x["match_score"], reverse=True)
        scores = [j["match_score"] for j in ranked_jobs]

        # Prepare insights placeholder for fallback
        insights = {"fallback": "Using simple matching due to LLM error"}

        # Compute career strategy even from fallback results
        try:
            career_strategy = _build_career_strategy(
                ranked_jobs,
                {
                    "total": len(ranked_jobs),
                    "avg_match": int(sum(scores) / len(scores)) if scores else 0,
                    "high_matches": len([s for s in scores if s >= 70]),
                },
                insights,
                jobs_data,
                resume_skills,
            )
        except Exception as e:
            print(f"[career_strategy] fallback error: {e}")
            career_strategy = {}

        return {
            "jobs": ranked_jobs[:limit],
            "summary": {
                "total": len(ranked_jobs),
                "avg_match": int(sum(scores) / len(scores)) if scores else 0,
                "high_matches": len([s for s in scores if s >= 70]),
                "medium_matches": len([s for s in scores if 60 <= s < 80]),
                "low_matches": len([s for s in scores if s < 60]),
            },
            "insights": insights,
            "career_strategy": career_strategy,
        }


SKILL_NORMALIZATION = {
    "react.js": "React",
    "reactjs": "React",
    "node.js": "Node",
    "nodejs": "Node",
    "javascript": "JavaScript",
    "java script": "JavaScript",
    "js": "JavaScript",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "python": "Python",
    "py": "Python",
    "sql": "SQL",
    "aws": "AWS",
    "amazon web services": "AWS",
    "gcp": "Google Cloud",
    "google cloud": "Google Cloud",
    "azure": "Azure",
    "docker": "Docker",
    "k8s": "Kubernetes",
    "kubernetes": "Kubernetes",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "redis": "Redis",
    "nginx": "Nginx",
    "linux": "Linux",
    "git": "Git",
    "github": "GitHub",
    "cicd": "CI/CD",
    "ci/cd": "CI/CD",
    "jenkins": "Jenkins",
    "graphql": "GraphQL",
    "rest api": "REST API",
    "rest": "REST API",
    "express": "Express",
    "express.js": "Express",
    "nextjs": "Next.js",
    "next.js": "Next.js",
    "vuejs": "Vue.js",
    "vue.js": "Vue.js",
    "angularjs": "Angular",
    "angular": "Angular",
    "django": "Django",
    "flask": "Flask",
    "spring": "Spring",
    "springboot": "Spring Boot",
    "spring boot": "Spring Boot",
    "fastapi": "FastAPI",
    "php": "PHP",
    "laravel": "Laravel",
    "ruby": "Ruby",
    "rails": "Ruby on Rails",
    "ruby on rails": "Ruby on Rails",
    "go": "Go",
    "golang": "Go",
    "rust": "Rust",
    "c#": "C#",
    "csharp": "C#",
    ".net": ".NET",
    "dotnet": ".NET",
    "swift": "Swift",
    "kotlin": "Kotlin",
    "scala": "Scala",
    "hadoop": "Hadoop",
    "spark": "Spark",
    "kafka": "Kafka",
    "rabbitmq": "RabbitMQ",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "puppeteer": "Puppeteer",
    "selenium": "Selenium",
    "cypress": "Cypress",
    "jest": "Jest",
    "mocha": "Mocha",
    "jquery": "jQuery",
    "sass": "Sass",
    "scss": "SCSS",
    "less": "Less",
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    "xml": "XML",
    "json": "JSON",
    "ajax": "AJAX",
    "axios": "Axios",
    "webpack": "Webpack",
    "vite": "Vite",
    "babel": "Babel",
    "eslint": "ESLint",
    "prettier": "Prettier",
    "figma": "Figma",
    "sketch": "Sketch",
    "photoshop": "Photoshop",
    "illustrator": "Illustrator",
    "after effects": "After Effects",
    "premiere": "Premiere Pro",
    "blender": "Blender",
    "unity": "Unity",
    "unreal": "Unreal Engine",
    "opencv": "OpenCV",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "keras": "Keras",
    "pillow": "Pillow",
    "numpy": "NumPy",
    "pandas": "Pandas",
    "scikit-learn": "Scikit-learn",
    "scipy": "SciPy",
    "matplotlib": "Matplotlib",
    "seaborn": "Seaborn",
    "plotly": "Plotly",
    "tableau": "Tableau",
    "powerbi": "Power BI",
    "excel": "Excel",
    "vba": "VBA",
    "statistics": "Statistics",
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "dl": "Deep Learning",
    "nlp": "NLP",
    "natural language processing": "NLP",
    "computer vision": "Computer Vision",
    "cv": "Computer Vision",
    "ai": "AI",
    "artificial intelligence": "AI",
    "data science": "Data Science",
    "data analysis": "Data Analysis",
    "data engineering": "Data Engineering",
    "etl": "ETL",
    "data warehouse": "Data Warehouse",
    "big data": "Big Data",
    "hive": "Hive",
    "presto": "Presto",
    "snowflake": "Snowflake",
    "databricks": "Databricks",
    "agile": "Agile",
    "scrum": "Scrum",
    "jira": "Jira",
    "kanban": "Kanban",
    "product management": "Product Management",
    "project management": "Project Management",
    "leadership": "Leadership",
    "communication": "Communication",
    "problem solving": "Problem Solving",
    "analytical thinking": "Analytical Thinking",
    "teamwork": "Teamwork",
}


def _normalize_skill(skill: str) -> str:
    """Normalize skill name using mapping."""
    normalized = skill.strip().lower()
    return SKILL_NORMALIZATION.get(normalized, skill.strip())


# Common tech skills for title-based extraction (fallback when skills column is empty)
TITLE_SKILLS = [
    "react",
    "node",
    "python",
    "java",
    "javascript",
    "sql",
    "aws",
    "docker",
    "kubernetes",
    "typescript",
    "angular",
    "vue",
    "django",
    "flask",
    "spring",
    "php",
    "ruby",
    "go",
    "rust",
    "c#",
    ".net",
    "swift",
    "kotlin",
    "scala",
    "mongodb",
    "postgresql",
    "mysql",
    "redis",
    "elasticsearch",
    "kafka",
    "rabbitmq",
    "graphql",
    "rest",
    "api",
    "express",
    "nextjs",
    "nuxt",
    "flutter",
    "react native",
    "aws",
    "azure",
    "gcp",
    "google cloud",
    "terraform",
    "ansible",
    "jenkins",
    "gitlab",
    "github",
    "ci/cd",
    "linux",
    "nginx",
    "apache",
    "tomcat",
    "hadoop",
    "spark",
    "tensorflow",
    "pytorch",
    "keras",
    "pandas",
    "numpy",
    "scikit-learn",
    "machine learning",
    "deep learning",
    "ai",
    "nlp",
    "computer vision",
    "data science",
    "etl",
    "tableau",
    "power bi",
    "excel",
    "vba",
    "agile",
    "scrum",
    "jira",
    "figma",
    "sketch",
    "laravel",
    "codeigniter",
    "wordpress",
    "shopify",
    "magento",
    "drupal",
    "seo",
    "google ads",
    "facebook ads",
    "analytics",
    "google analytics",
    "postman",
    "git",
]


def _extract_skills_from_title(title: str) -> list:
    """Extract skills from job title as fallback."""
    if not title:
        return []
    title_lower = title.lower()
    found = []
    for skill in TITLE_SKILLS:
        if skill in title_lower:
            found.append(skill)
    return found


@router.get("/market-pulse")
def get_market_pulse(
    view: str = "skills",
    user=Depends(current_user),
):
    """
    Returns market pulse data with skill/title frequency and WoW deltas.
    Computes current period (last 7 days) vs previous period (days 8-14) dynamically.
    Falls back to all user jobs if created_at is empty.
    """
    import datetime as dt

    uid = int(user["sub"])
    now = dt.datetime.now()
    current_start = (now - dt.timedelta(days=7)).strftime("%Y-%m-%d")
    previous_start = (now - dt.timedelta(days=14)).strftime("%Y-%m-%d")
    previous_end = (now - dt.timedelta(days=7)).strftime("%Y-%m-%d")

    with get_db() as db:
        # Check if we have any jobs with non-empty created_at
        has_dates = (
            db.execute(
                "SELECT COUNT(*) FROM jobs WHERE user_id = ? AND is_deleted = 0 AND created_at IS NOT NULL AND created_at != ''",
                (uid,),
            ).fetchone()[0]
            > 0
        )

        if view == "skills":
            if has_dates:
                # Use date-filtered query
                current_rows = db.execute(
                    """
                    SELECT skills, title FROM jobs
                    WHERE user_id = ? AND is_deleted = 0
                    AND created_at >= ?
                    """,
                    (uid, current_start),
                ).fetchall()

                previous_rows = db.execute(
                    """
                    SELECT skills, title FROM jobs
                    WHERE user_id = ? AND is_deleted = 0
                    AND created_at >= ? AND created_at < ?
                    """,
                    (uid, previous_start, previous_end),
                ).fetchall()
            else:
                # Fallback: query all non-deleted jobs (no date filter)
                current_rows = db.execute(
                    """
                    SELECT skills, title FROM jobs
                    WHERE user_id = ? AND is_deleted = 0
                    """,
                    (uid,),
                ).fetchall()
                # For fallback, empty previous
                previous_rows = []
        else:
            if has_dates:
                current_rows = db.execute(
                    """
                    SELECT title FROM jobs
                    WHERE user_id = ? AND is_deleted = 0 AND title IS NOT NULL
                    AND created_at >= ?
                    """,
                    (uid, current_start),
                ).fetchall()

                previous_rows = db.execute(
                    """
                    SELECT title FROM jobs
                    WHERE user_id = ? AND is_deleted = 0 AND title IS NOT NULL
                    AND created_at >= ? AND created_at < ?
                    """,
                    (uid, previous_start, previous_end),
                ).fetchall()
            else:
                current_rows = db.execute(
                    """
                    SELECT title FROM jobs
                    WHERE user_id = ? AND is_deleted = 0 AND title IS NOT NULL
                    """,
                    (uid,),
                ).fetchall()
                previous_rows = []

    current_count = len(current_rows)
    previous_count = len(previous_rows)

    current_items = Counter()
    previous_items = Counter()

    # Process current period
    for row in current_rows:
        if view == "skills":
            skills_str = row[0] if row[0] else ""
            title_str = row[1] if row[1] else ""
            # Use skills column, fallback to title extraction
            if skills_str:
                for skill in skills_str.split(","):
                    skill = skill.strip()
                    if skill:
                        normalized = _normalize_skill(skill)
                        current_items[normalized] += 1
            else:
                # Fallback: extract from title
                for skill in _extract_skills_from_title(title_str):
                    normalized = _normalize_skill(skill)
                    current_items[normalized] += 1
        else:
            title = row[0] if row[0] else ""
            if title:
                current_items[title] += 1

    # Process previous period
    for row in previous_rows:
        if view == "skills":
            skills_str = row[0] if row[0] else ""
            title_str = row[1] if row[1] else ""
            if skills_str:
                for skill in skills_str.split(","):
                    skill = skill.strip()
                    if skill:
                        normalized = _normalize_skill(skill)
                        previous_items[normalized] += 1
            else:
                for skill in _extract_skills_from_title(title_str):
                    normalized = _normalize_skill(skill)
                    previous_items[normalized] += 1
        else:
            title = row[0] if row[0] else ""
            if title:
                previous_items[title] += 1

    all_items = set(current_items.keys()) | set(previous_items.keys())
    total_current = current_count or 1
    total_previous = previous_count or 1

    result_data = []
    for name in all_items:
        curr = current_items.get(name, 0)
        prev = previous_items.get(name, 0)
        curr_pct = round((curr / total_current) * 100, 1)
        prev_pct = round((prev / total_previous) * 100, 1)
        delta = round(curr_pct - prev_pct, 1)

        if delta > 5:
            trend = "up"
        elif delta < -5:
            trend = "down"
        else:
            trend = "stable"

        result_data.append(
            {
                "name": name,
                "current": curr,
                "previous": prev,
                "current_pct": curr_pct,
                "previous_pct": prev_pct,
                "delta": delta,
                "trend": trend,
            }
        )

    result_data.sort(key=lambda x: x["current_pct"], reverse=True)
    result_data = result_data[:20]

    return {
        "view": view,
        "data": result_data,
        "last_updated": now.isoformat(),
        "total_jobs_analyzed": current_count + previous_count,
    }
