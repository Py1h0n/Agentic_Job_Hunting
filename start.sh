#!/bin/bash
cd backend
pip install -r ../requirements.txt
playwright install chromium --with-deps
uvicorn main:app --host 0.0.0.0 --port $PORT
