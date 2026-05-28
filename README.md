# SaaS RAG Agent

Project structure:

- `frontend/` -> React GPT-style chat UI
- `backend/` -> FastAPI + LangGraph + RAG backend
- `.venv/` -> optional shared Python virtual environment

## Tech Stack

| Package             | Purpose                                                                     |
| ------------------- | --------------------------------------------------------------------------- |
| `phidata`           | Framework for building AI agents, RAG, workflows, and tool-using assistants |
| `python-dotenv`     | Loads `.env` environment variables (API keys, configs)                      |
| `yfinance`          | Fetches stock market and finance data from Yahoo Finance                    |
| `packaging`         | Handles Python package/version management                                   |
| `duckduckgo-search` | Lets AI agents perform web searches using DuckDuckGo                        |
| `fastapi`           | High-performance backend API framework for AI apps                          |
| `uvicorn`           | ASGI server to run FastAPI applications                                     |
| `groq`              | SDK/API client for using Groq ultra-fast LLM inference                      |

## Run Backend

```powershell
python -m venv .venv
.venv\Scripts\activate
cd backend
copy .env.example .env
pip install -r requirements.txt
pip install -e .
python -m uvicorn app.main:app --reload
```

Backend docs:

[backend/app/main.py](C:/Users/kulde/Desktop/AI/backend/app/main.py:1)

## Run Frontend

```powershell
cd frontend
npm install
npm run dev
```

Frontend URL:

```text
http://127.0.0.1:5173
```

## Notes

- The React app proxies API calls to `http://127.0.0.1:8000`.
- Backend env files live in `backend/.env` and `backend/.env.example`.
- Provider keys are read from env vars; they are not hardcoded into source files.
- Query logs and stored chunks are now persisted to PostgreSQL when `POSTGRES_URL` is set.
- If you already have the backend running from the old root path, stop it and restart from `backend/`.
