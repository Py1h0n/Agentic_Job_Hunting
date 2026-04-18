#!/bin/bash
cd backend
pip install -r ../requirements.txt -q
echo "Installing Playwright browsers..."
playwright install chromium 2>&1 || echo "Playwright install may have issues"
uvicorn main:app --host 0.0.0.0 --port $PORT
