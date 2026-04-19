#!/bin/bash
cd backend
pip install -r ../requirements.txt -q
echo "Installing Playwright browsers with dependencies..."
playwright install-deps chromium 2>/dev/null || apt-get update && apt-get install -y libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 libpango-1.0-0 libcairo2 2>/dev/null || true
playwright install chromium 2>&1 || true
uvicorn main:app --host 0.0.0.0 --port $PORT