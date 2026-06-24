# LoopForge

**Production-grade loop engineering agentic AI system** — an autonomous agent that iteratively executes, critiques, and refines its own outputs until convergence.

---

## Overview

LoopForge implements a self-improving loop pattern using LangGraph. Each task runs through a graph of specialized nodes: an **Executor** that uses tools to answer the task, a **Critic** that scores the output across multiple quality dimensions, a **Refiner** that improves it based on the critique, and a **Meta** node that stores strategy memory for future tasks. The loop continues until the output score crosses a convergence threshold or a hard iteration cap is reached.

```
Input
  │
  ▼
┌─────────────┐
│  Executor   │  ← ReAct pattern (Thought → Action → Observation)
│  (Groq LLM) │  ← Tools: web search, calculator, yfinance, python repl
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Critic    │  ← Scores: factuality, completeness, clarity, task_alignment
│  (score/10) │  ← Weighted overall score
└──────┬──────┘
       │
       ▼
┌─────────────┐     score ≥ 7.5  ──▶ ┌──────┐
│   Router    │ ─────────────────────▶│ Meta │──▶ END
│             │     max iterations ──▶│      │
└──────┬──────┘                       └──────┘
       │ score < threshold
       ▼
┌─────────────┐
│   Refiner   │  ← Improves output using specific critique reasoning
└──────┬──────┘
       │
       └────────────────────────────▶ Executor (next iteration)
```

---

## Features

- **Self-improving loop** — executor → critic → refiner cycle with configurable convergence threshold
- **ReAct executor** — Thought/Action/Observation reasoning pattern with real tool use
- **Structured critic** — 4-axis rubric scoring with few-shot examples and score anchors
- **Meta loop memory** — ChromaDB stores task strategies per user; top-3 similar past tasks inform future runs
- **Circuit breaker** — stops early if scores decline for 2 consecutive iterations
- **JWT authentication** — access tokens (15 min) + refresh tokens (7 days, hashed in DB)
- **Role-based access control** — `free`, `pro`, `admin` roles with per-role tool access and iteration limits
- **Input sanitization** — prompt injection detection, HTML stripping, length enforcement
- **Rate limiting** — IP-level (slowapi) + per-user hourly limits (Redis)
- **Async Celery workers** — each task runs in an isolated worker with 300s hard timeout
- **LangFuse tracing** — per-iteration spans with scores, latency, and token counts
- **Streamlit dashboard** — real-time score chart, loop progress, convergence status

---

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph |
| API | FastAPI + uvicorn |
| LLM (primary) | Groq — `llama-3.1-8b-instant` |
| LLM (fallback) | HuggingFace — `Meta-Llama-3.1-8B-Instruct` |
| Tools | Tavily (search), yfinance, calculator, sandboxed Python REPL |
| Auth | python-jose (JWT) + passlib (bcrypt) |
| Rate limiting | slowapi + Redis |
| Database | PostgreSQL (asyncpg) + pgvector |
| Cache | Redis |
| Vector memory | ChromaDB |
| Task queue | Celery + Redis broker |
| Observability | LangFuse + Sentry |
| UI | Streamlit |

---

## Project Structure

```
loopforge/
├── main.py                    # FastAPI app entry point
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── core/
│   ├── graph.py               # LangGraph state graph
│   ├── state.py               # GraphState TypedDict
│   ├── router.py              # Conditional edge logic
│   ├── cache.py               # Redis result cache
│   └── nodes/
│       ├── executor.py        # ReAct agent with tool use
│       ├── critic.py          # Rubric scorer (4 axes)
│       ├── refiner.py         # Critique-driven improver
│       └── meta.py            # Strategy memory + status resolution
├── tools/
│   ├── search.py              # Tavily web search
│   ├── calculator.py          # AST-safe math evaluator
│   ├── python_repl.py         # Sandboxed Python executor
│   └── yfinance_tool.py       # Market data
├── auth/
│   ├── jwt.py                 # Token creation + verification
│   ├── rbac.py                # Role definitions + permission checks
│   └── middleware.py          # FastAPI auth middleware
├── security/
│   ├── sanitizer.py           # Input validation + injection detection
│   ├── rate_limiter.py        # slowapi + Redis rate limiting
│   └── error_handler.py       # Global exception handler
├── api/
│   ├── schemas.py             # Pydantic request/response models
│   └── routes/
│       ├── tasks.py           # POST /tasks/run-task, GET /tasks/task/{id}
│       ├── auth.py            # POST /auth/register, /login, /refresh
│       └── health.py          # GET /health
├── db/
│   ├── postgres.py            # Async connection pool
│   ├── redis_client.py        # Redis client
│   └── models.py              # Table DDL
├── memory/
│   └── chroma.py              # ChromaDB client (user-scoped)
├── workers/
│   └── celery_app.py          # Celery task definition
├── observability/
│   ├── langfuse_client.py     # Trace + span management
│   └── sentry_setup.py        # Sentry initialization
└── ui/
    └── app.py                 # Streamlit dashboard
```

---

## Quickstart

### Prerequisites

- Python 3.11
- Docker + Docker Compose
- API keys (see below)

### 1. Clone and configure

```bash
git clone https://github.com/Sahojit/Loop-Forge.git
cd Loop-Forge
cp .env.example .env
```

Edit `.env` and fill in the required keys:

```env
HUGGINGFACE_API_KEY=hf_...       # huggingface.co/settings/tokens
GROQ_API_KEY=gsk_...             # console.groq.com/keys
TAVILY_API_KEY=tvly-...          # app.tavily.com
JWT_SECRET_KEY=                  # run: openssl rand -hex 32
```

### 2. Start infrastructure

```bash
docker compose up postgres redis -d
```

### 3. Create virtualenv and install dependencies

```bash
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Start the API

```bash
PYTHONPATH=. uvicorn main:app --host 0.0.0.0 --port 8010
```

### 5. Start the Celery worker

```bash
PYTHONPATH=. celery -A workers.celery_app worker --loglevel=info --concurrency=2
```

### 6. Start the UI

```bash
streamlit run ui/app.py --server.port 8503
```

Open [http://localhost:8503](http://localhost:8503)

---

## API Reference

### Auth

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/auth/register` | Register a new user |
| `POST` | `/auth/login` | Login, returns access + refresh tokens |
| `POST` | `/auth/refresh` | Rotate refresh token |

### Tasks

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/tasks/run-task` | Submit a task (queued to Celery) |
| `GET` | `/tasks/task/{id}` | Poll task status + result |

### Health

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Service health check |

Interactive docs: [http://localhost:8010/docs](http://localhost:8010/docs)

---

## Role Permissions

| Role | Max Iterations | Tasks/Hour | Tools |
|---|---|---|---|
| `free` | 2 | 5 | tavily, calculator |
| `pro` | 5 | 100 | tavily, calculator, yfinance, python_repl |
| `admin` | 10 | unlimited | all |

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `CONVERGENCE_THRESHOLD` | `7.5` | Minimum score to stop the loop |
| `MAX_ITERATIONS_DEFAULT` | `5` | Default loop cap |
| `TOKEN_BUDGET_PER_TASK` | `8000` | Max tokens before BudgetExceededError |
| `ENVIRONMENT` | `development` | Controls Sentry environment tag |

---

## Security

- All database queries use parameterized form (`$1`, `$2`) — no string interpolation
- Every query scoped to `user_id` — no cross-user data leakage
- ChromaDB always filters by `user_id` in metadata
- JWT refresh tokens stored as SHA-256 hashes, rotated on every use
- Error responses never include stack traces, file paths, or env var names
- Python REPL sandboxed with blocked import patterns and restricted builtins
- Sentry `before_send` scrubs request body before transmission

---

## Observability

LangFuse traces every task with:
- Root trace: `task_id`, `user_id`, `role`, `input_length`, `max_iterations`
- Per-iteration span: `node`, `score`, `tokens_used`, `latency_ms`
- Final span: `converged`, `total_iterations`, `final_score`, `total_tokens`

Raw inputs and outputs are never logged — only lengths (PII protection).

---

## License

MIT
