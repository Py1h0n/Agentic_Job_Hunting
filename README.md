# JobScout - AI-Powered Job Search Platform

<p align="center">
  <a href="https://railway.app"><img src="https://img.shields.io/badge/Deploy-Railway-blue?style=flat&logo=railway"></a>
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.12+-blue?style=flat&logo=python"></a>
  <a href="https://fastapi.tiangolo.com"><img src="https://img.shields.io/badge/FastAPI-0.115+-00a393?style=flat&logo=fastapi"></a>
</p>

AI-powered job search platform with automated job scraping, intelligent resume parsing, and personalized job matching.

## Features

- 🤖 **AI Job Scraping** - Automated job aggregation from multiple job sites (BDJobs, SkillJobs, Niyog, NextJobz, JobMedia, CareerJet, ShomVob)
- 📄 **Resume Parser** - AI-powered resume parsing and analysis
- 🎯 **Smart Matching** - AI-driven job matching based on your profile
- 📊 **Insights Dashboard** - Track job search analytics
- 💾 **Saved Jobs** - Save and organize favorite job listings

## Tech Stack

- **Backend**: FastAPI (Python)
- **Database**: SQLite
- **AI**: OpenAI GPT-4
- **Browser Automation**: Browser-Use (Playwright)
- **Deployment**: Railway

## Getting Started

### Prerequisites

- Python 3.12+
- OpenAI API Key

### Installation

```bash
# Clone the repository
git clone https://github.com/YOUR_USERNAME/jobsearch-app.git
cd jobsearch-app

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt

# Run the application
cd backend
uvicorn main:app --reload
```

Visit http://localhost:8000

### Environment Variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key_here
SECRET_KEY=your_secret_key_here
```

## Deployment

Deploy to Railway with one click:

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app)

Or connect your GitHub repository in the Railway dashboard.

## Project Structure

```
├── backend/
│   ├── agents/          # Job scraping agents
│   ├── routers/        # API routes
│   ├── main.py        # FastAPI app
│   └── database.py    # Database operations
├── frontend/           # Static HTML frontend
├── .env              # Environment variables
├── requirements.txt  # Python dependencies
└── railway.json      # Railway configuration
```

## License

MIT License - see LICENSE for details.