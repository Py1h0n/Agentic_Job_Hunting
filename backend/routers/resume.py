import base64
import json
import os
import uuid
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

RESUME_ANALYZER_PROMPT = """You are a resume analyzer. Analyze this resume and extract:
1. Skills - programming languages, frameworks, tools, technologies (list as array)
2. Work experience - years of experience and roles (string like "2 years" or "5+ years")  
3. Education - degrees, institutions, graduation years (list as array of objects)
4. Summary - 2-3 sentences about the candidate's background and expertise

Return ONLY a JSON object with these keys:
{
  "skills": ["Python", "React", "SQL", "AWS"],
  "experience": "3 years",
  "education": [{"degree": "BSc in Computer Science", "institution": "AUST", "year": "2020"}],
  "summary": "Experienced backend developer..."
}

If a field cannot be determined, use empty array or empty string.""".strip()

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


def _analyze_image(image_b64: str) -> dict:
    client = _get_llm_client()
    if not client:
        return {
            "skills": [],
            "experience": "",
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

            return json.loads(content)
    except Exception as e:
        print(f"[resume] Gemma analysis failed: {e}")
        return {
            "skills": [],
            "experience": "Error",
            "education": [],
            "summary": f"Analysis failed: {str(e)}",
        }

    return {
        "skills": [],
        "experience": "",
        "education": [],
        "summary": "No content extracted",
    }


def _analyze_text(text: str) -> dict:
    client = _get_llm_client()
    if not client:
        return {
            "skills": [],
            "experience": "",
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
        "skills": [],
        "experience": "",
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

        if existing:
            db.execute(
                """UPDATE resumes SET 
                    filename=?, file_type=?, file_path=?, extracted_text=?,
                    skills=?, experience=?, education=?, summary=?,
                    updated_at=datetime('now')
                WHERE user_id=?""",
                (
                    file.filename,
                    ext,
                    str(file_path),
                    text if ext != "jpg" and ext != "png" else None,
                    json.dumps(analysis.get("skills", [])),
                    analysis.get("experience", ""),
                    json.dumps(analysis.get("education", [])),
                    analysis.get("summary", ""),
                    uid,
                ),
            )
        else:
            db.execute(
                """INSERT INTO resumes 
                    (user_id, filename, file_type, file_path, extracted_text,
                     skills, experience, education, summary)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    uid,
                    file.filename,
                    ext,
                    str(file_path),
                    text if ext != "jpg" and ext != "png" else None,
                    json.dumps(analysis.get("skills", [])),
                    analysis.get("experience", ""),
                    json.dumps(analysis.get("education", [])),
                    analysis.get("summary", ""),
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

    if row["skills"] and row["summary"]:
        return {"status": "ready"}

    return {"status": "processing"}


@router.get("")
def get_resume(user=Depends(current_user)):
    uid = int(user["sub"])
    with get_db() as db:
        row = db.execute("SELECT * FROM resumes WHERE user_id=?", (uid,)).fetchone()
    if not row:
        return None
    r = dict(row)
    r["skills"] = json.loads(r.get("skills", "[]"))
    r["education"] = json.loads(r.get("education", "[]"))
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
        content = content.strip("```json").strip("```").strip()
        result = json.loads(content)
        return result
    except Exception as e:
        print(f"[match] failed: {e}")
        return {"score": 0, "reason": "Analysis failed"}


@router.get("/match/{job_id}/breakdown")
def match_breakdown(job_id: int, user=Depends(current_user)):
    uid = int(user["sub"])

    with get_db() as db:
        resume_row = db.execute(
            "SELECT * FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()
        job_row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()

    if not resume_row or not job_row:
        raise HTTPException(404, "Resume or job not found")

    resume = dict(resume_row)
    job = dict(job_row)
    resume_skills = json.loads(resume.get("skills", "[]"))
    job_skills_str = job.get("skills", "") or ""
    job_skills_list = [
        s.strip().lower() for s in job_skills_str.split(",") if s.strip()
    ]

    matched = [s for s in resume_skills if s.lower() in job_skills_list]
    missing = [
        s for s in job_skills_list if s not in [rs.lower() for rs in resume_skills]
    ]

    skills_pct = (
        min(100, int((len(matched) / max(len(job_skills_list), 1)) * 100))
        if job_skills_list
        else 50
    )

    resume_exp = resume.get("experience", "") or ""
    job_exp = job.get("experience", "") or ""
    exp_pct = 50
    try:
        r_yrs = (
            int("".join(filter(str.isdigit, resume_exp.split()[0])) or 0)
            if resume_exp
            else 0
        )
        j_yrs = (
            int("".join(filter(str.isdigit, job_exp.split()[0])) or 0) if job_exp else 0
        )
        if j_yrs > 0:
            exp_pct = 100 if r_yrs >= j_yrs else max(0, int((r_yrs / j_yrs) * 100))
        else:
            exp_pct = 80
    except:
        pass

    overall = int(skills_pct * 0.6 + exp_pct * 0.4)

    return {
        "overall": overall,
        "skills_match": {
            "score": skills_pct,
            "matched": matched,
            "missing": missing[:5],
        },
        "experience_match": {
            "score": exp_pct,
            "summary": f"You have {resume_exp or 'unknown'} experience. Job requires {job_exp or 'not specified'}.",
        },
    }


@router.get("/job/{job_id}/insight")
def job_insight(job_id: int, user=Depends(current_user)):
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
    job_skills = job.get("skills", "") or ""

    prompt = f"""Given this resume:
Skills: {", ".join(resume_skills)}

And this job:
Title: {job.get("title", "")}
Company: {job.get("company", "")}
Requirements: {job_skills}

Provide a brief insight (1-2 sentences) explaining:
1. Why this job matches (if it does)
2. Any missing skills from the resume

Return ONLY JSON:
{{"insight": "Matches your React & frontend experience. Missing: Node.js, TypeScript"}}""".strip()

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
                    "content": "You provide brief job insights. Return JSON.",
                },
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
        )
        content = response.choices[0].message.content.strip()
        content = content.strip("```json").strip("```").strip()
        result = json.loads(content)
        return result
    except Exception as e:
        print(f"[insight] failed: {e}")
        return {"insight": ""}


@router.post("/applied/{job_id}")
def mark_applied(job_id: int, user=Depends(current_user)):
    uid = int(user["sub"])

    with get_db() as db:
        existing = db.execute(
            "SELECT id FROM applied_jobs WHERE user_id=? AND job_id=?", (uid, job_id)
        ).fetchone()

        if not existing:
            db.execute(
                "INSERT INTO applied_jobs (user_id, job_id) VALUES (?, ?)",
                (uid, job_id),
            )
        else:
            db.execute(
                "DELETE FROM applied_jobs WHERE user_id=? AND job_id=?", (uid, job_id)
            )

    return {"status": "ok"}


@router.get("/applied")
def get_applied(user=Depends(current_user)):
    uid = int(user["sub"])

    with get_db() as db:
        rows = db.execute(
            """
            SELECT j.id, j.title, j.company, j.location, j.url, a.applied_at
            FROM applied_jobs a
            JOIN jobs j ON a.job_id = j.id
            WHERE a.user_id = ?
            ORDER BY a.applied_at DESC
        """,
            (uid,),
        ).fetchall()

    return [dict(r) for r in rows]


@router.get("/top-jobs")
def get_top_matching_jobs(
    limit: int = 10, search_id: int | None = None, user=Depends(current_user)
):
    uid = int(user["sub"])

    with get_db() as db:
        resume_row = db.execute(
            "SELECT * FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()

        if search_id:
            # Get jobs for a specific search
            saved_rows = db.execute(
                "SELECT * FROM jobs WHERE user_id=? AND search_id=?", (uid, search_id)
            ).fetchall()
        else:
            # Get ALL jobs from user's searches (not just saved ones)
            saved_rows = db.execute(
                "SELECT * FROM jobs WHERE user_id=? AND is_deleted=0 ORDER BY id DESC LIMIT 100",
                (uid,),
            ).fetchall()

    if not resume_row:
        return {"jobs": [], "summary": {"error": "No resume found"}}

    resume = dict(resume_row) if resume_row else {}
    resume_skills = json.loads(resume.get("skills", "[]"))
    resume_exp = resume.get("experience", "")

    def calc_match_score(job_skills_str: str, job_exp: str) -> dict:
        job_skills_list = (
            [s.strip().lower() for s in job_skills_str.split(",")]
            if job_skills_str
            else []
        )

        matched = [s for s in resume_skills if s.lower() in job_skills_list]
        missing = [
            s
            for s in job_skills_list
            if s.lower() not in [rs.lower() for rs in resume_skills]
        ]

        skills_match = (
            min(100, int((len(matched) / max(len(job_skills_list), 1)) * 100))
            if job_skills_list
            else 50
        )

        exp_match = 50
        if resume_exp and job_exp:
            try:
                resume_years = int(
                    "".join(filter(str.isdigit, resume_exp.split()[0])) or 0
                )
                job_years = int("".join(filter(str.isdigit, job_exp.split()[0])) or 0)
                if resume_years >= job_years:
                    exp_match = 100
                else:
                    exp_match = max(0, int((resume_years / job_years) * 100))
            except:
                exp_match = 50

        return {
            "score": int((skills_match * 0.6) + (exp_match * 0.4)),
            "matched_skills": matched,
            "missing_skills": missing[:5],
        }

    ranked_jobs = []
    for row in saved_rows:
        job = dict(row) if row else {}
        match = calc_match_score(job.get("skills", ""), job.get("experience", ""))

        job_skills = job.get("skills", "") or ""
        reason = f"Matched on {len(match['matched_skills'])} skills"
        if match["missing_skills"]:
            reason += f", missing {len(match['missing_skills'])} skills"

        ranked_jobs.append(
            {
                "id": job.get("id"),
                "title": job.get("title"),
                "company": job.get("company"),
                "location": job.get("location"),
                "url": job.get("url"),
                "match_score": match["score"],
                "match_reason": reason,
                "missing_skills": match["missing_skills"],
            }
        )

    ranked_jobs.sort(key=lambda x: x["match_score"], reverse=True)
    top_jobs = ranked_jobs[:limit]

    summary = {}
    if top_jobs:
        scores = [j["match_score"] for j in top_jobs]
        summary = {
            "best_role": top_jobs[0]["title"],
            "avg_match": int(sum(scores) / len(scores)),
            "top_missing": list(set(sum([j["missing_skills"] for j in top_jobs], [])))[
                :5
            ],
            "jobs_found": len(ranked_jobs),
        }

    return {"jobs": top_jobs, "summary": summary}


def _generate_action_plans(
    resume_skills: list, top_skills: list, missing_skills: list
) -> dict:
    """Generate AI-powered personalized action plans for missing skills"""
    if not missing_skills:
        return {}

    # Build prompt for action plans
    resume_str = ", ".join(resume_skills) if resume_skills else "None listed"
    market_str = ", ".join(top_skills[:8]) if top_skills else "General tech skills"
    missing_str = ", ".join(missing_skills)

    prompt = f"""You are a career coach. Given this resume and market demand:

Resume skills: {resume_str}
Market demand skills: {market_str}
Missing skills: {missing_str}

For each MISSING skill, provide a SHORT one-sentence action plan (max 15 words) for how to learn or pivot around this skill.

Return ONLY a JSON object like:
{{
  "python": "Take a Python bootcamp or complete Python.org tutorial within 2 weeks",
  "react": "Build a small React project to demonstrate frontend skills quickly",
  "aws": "Study AWS Free Tier and earn Cloud Practitioner certification"
}}

Be specific and actionable. Focus on FAST learning strategies."""

    try:
        from openai import OpenAI
        import os

        client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY", ""),
        )

        response = client.chat.completions.create(
            model="Qwen/Qwen3-235B-A22B-Instruct-2507",
            messages=[
                {"role": "system", "content": "You are a helpful career coach."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=300,
            temperature=0.3,
        )

        content = response.choices[0].message.content.strip()

        # Extract JSON from response
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        return json.loads(content)
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


@router.get("/insights")
def get_insights(search_id: int | None = None, user=Depends(current_user)):
    from database import get_column

    uid = int(user["sub"])

    with get_db() as db:
        resume_row = db.execute(
            "SELECT * FROM resumes WHERE user_id=?", (uid,)
        ).fetchone()

        # Get only SAVED jobs for personalized insights
        if search_id:
            saved_rows = db.execute(
                "SELECT * FROM jobs WHERE user_id=? AND search_id=? AND saved=1 AND is_deleted=0",
                (uid, search_id),
            ).fetchall()
        else:
            saved_rows = db.execute(
                "SELECT * FROM jobs WHERE user_id=? AND saved=1 AND is_deleted=0 ORDER BY id DESC LIMIT 100",
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

    return {
        "insights": insights,
        "summary": {
            "best_role": "Based on your skills",
            "avg_match": f"{avg_match}%",
            "top_missing": missing[:5],
            "jobs_found": len(saved_rows),
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
    limit: int = 20,
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
                }
            )

        # Send initial count
        yield f"data: {json.dumps({'type': 'start', 'total': len(jobs_data)})}\n\n"

        # Send "analyzing" status
        yield f"data: {json.dumps({'type': 'status', 'message': 'Starting AI analysis...'})}\n\n"

        # Analyze each job asynchronously
        from openai import OpenAI

        client = OpenAI(
            base_url="https://api.tokenfactory.nebius.com/v1/",
            api_key=os.environ.get("NEBIUS_API_KEY", ""),
        )

        # Process jobs in smaller batches and stream results as they complete
        analyzed = []
        for idx, job in enumerate(jobs_data):
            try:
                # Create a prompt for single job analysis
                prompt = f"""Analyze this job for a candidate with:
- Skills: {", ".join(resume_skills)}
- Experience: {resume_exp}

Job: {job["title"]} at {job["company"]}
Skills required: {job.get("skills", "Not specified")}
Experience: {job.get("experience", "Not specified")}

Return ONLY JSON with keys: score (0-100), match_reason (string), missing_skills (array), strengths (array)"""

                response = client.chat.completions.create(
                    model=RESUME_MODEL,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a job matching expert. Return ONLY valid JSON.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=500,
                    temperature=0.3,
                )

                content = response.choices[0].message.content.strip()
                content = content.strip("```json").strip("```").strip()
                result = json.loads(content)

                analysis = {
                    "score": result.get("score", 50),
                    "reason": result.get("match_reason", ""),
                    "missing": result.get("missing_skills", []),
                    "strengths": result.get("strengths", []),
                }
            except Exception as e:
                print(f"[stream] Job {job['id']} analysis failed: {e}")
                # Fallback simple matching
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

                analysis = {
                    "score": score,
                    "reason": f"Matched on {len(matched)} skills"
                    + (f", missing {len(missing)}" if missing else ""),
                    "missing": missing[:5],
                    "strengths": matched,
                }

            # Get saved status
            with get_db() as db:
                saved_row = db.execute(
                    "SELECT saved FROM jobs WHERE id=? AND user_id=?", (job["id"], uid)
                ).fetchone()
                saved = saved_row["saved"] if saved_row else 0

            job_result = {
                "id": job["id"],
                "title": job["title"],
                "company": job["company"],
                "location": job["location"],
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
            yield f"data: {json.dumps({'type': 'job', 'job': job_result, 'index': idx, 'total': len(jobs_data)})}\n\n"

        # Sort by score and send final results
        analyzed.sort(key=lambda x: x["match_score"], reverse=True)

        scores = [j["match_score"] for j in analyzed]
        avg_score = int(sum(scores) / len(scores)) if scores else 0

        summary = {
            "total": len(analyzed),
            "avg_match": avg_score,
            "high_matches": len([s for s in scores if s >= 80]),
            "medium_matches": len([s for s in scores if 60 <= s < 80]),
            "low_matches": len([s for s in scores if s < 60]),
        }

        yield f"data: {json.dumps({'type': 'done', 'jobs': analyzed, 'summary': summary})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/analyze-jobs")
def analyze_all_jobs(
    limit: int = 20,
    search_id: Optional[int] = None,
    session_id: Optional[str] = None,
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
            return {"jobs": [], "summary": {"error": "No resume found"}, "insights": {}}

        resume = dict(resume_row)
        resume_skills = json.loads(resume.get("skills", "[]"))
        resume_exp = resume.get("experience", "")
        resume_summary = resume.get("summary", "")

        # Get all jobs (not just saved ones)
        if session_id:
            # Use session_id (UUID) - join with searches table
            jobs_rows = db.execute(
                "SELECT j.* FROM jobs j "
                "JOIN searches s ON j.search_id = s.id "
                "WHERE s.session_id=? AND j.user_id=? AND j.is_deleted=0 ORDER BY j.id DESC LIMIT ?",
                (session_id, uid, limit),
            ).fetchall()
        elif search_id:
            # Use search_id (integer)
            jobs_rows = db.execute(
                "SELECT * FROM jobs WHERE user_id=? AND search_id=? AND is_deleted=0 ORDER BY id DESC LIMIT ?",
                (uid, search_id, limit),
            ).fetchall()
        else:
            # Get all jobs
            jobs_rows = db.execute(
                "SELECT * FROM jobs WHERE user_id=? AND is_deleted=0 ORDER BY id DESC LIMIT ?",
                (uid, limit),
            ).fetchall()

        if not jobs_rows:
            return {"jobs": [], "summary": {"total": 0}, "insights": {}}

    # Build prompt for batch analysis
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
        avg_score = int(sum(scores) / len(scores) if scores else 0)

        return {
            "jobs": ranked_jobs[:limit],
            "summary": {
                "total": len(ranked_jobs),
                "avg_match": int(sum(scores) / len(scores)) if scores else 0,
                "high_matches": len([s for s in scores if s >= 80]),
                "medium_matches": len([s for s in scores if 60 <= s < 80]),
                "low_matches": len([s for s in scores if s < 60]),
            },
            "insights": insights,
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

        return {
            "jobs": ranked_jobs[:limit],
            "summary": {
                "total": len(ranked_jobs),
                "avg_match": int(sum(scores) / len(scores)) if scores else 0,
                "high_matches": len([s for s in scores if s >= 80]),
                "medium_matches": len([s for s in scores if 60 <= s < 80]),
                "low_matches": len([s for s in scores if s < 60]),
            },
            "insights": {"fallback": "Using simple matching due to LLM error"},
        }
