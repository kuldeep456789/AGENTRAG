# Backend Service

FastAPI backend for the SaaS RAG agent.

## Run

```powershell
cd C:\Users\kulde\Desktop\AI
.venv\Scripts\activate
cd backend
copy .env.example .env
pip install -r requirements.txt
pip install -e .
python app.py
```

`python app.py` automatically re-launches with `..\.venv\Scripts\python.exe` when you forget to activate the venv. You can also run:

```powershell
..\.venv\Scripts\python.exe app.py
```
You can also run:
```powershell
python -m uvicorn app.main:app --reload
```
Add your provider keys and PostgreSQL URL to `backend/.env`.
Example variable names:

- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`
- `CLAUDE_API_KEY`
- `GROQ_API_KEY`
- `POSTGRES_URL`

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

## Main Files

- [app.py](C:/Users/kulde/Desktop/AI/backend/app.py:1)
- [app/main.py](C:/Users/kulde/Desktop/AI/backend/app/main.py:1)
- [app/workflows/rag.py](C:/Users/kulde/Desktop/AI/backend/app/workflows/rag.py:1)
- [app/services/providers.py](C:/Users/kulde/Desktop/AI/backend/app/services/providers.py:1)

## Endpoints

- `POST /auth/login`
- `POST /auth/refresh`
- `POST /query`
- `POST /input`
- `POST /summarize`
- `POST /vision`
- `POST /finance/quote`
- `POST /agents/phidata`
- `GET /dashboard`
- `GET /health`
- `GET /knowledge/web/list`
- `GET /knowledge/web/page`
- `DELETE /knowledge/web/page`
- `GET /stack`
