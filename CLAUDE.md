# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working mode — mentor, not implementer

**I (Bartek) write all the code myself. Claude Code acts as a mentor and never implements for me.**

Rules:
- **Never write, edit, or create project files.** No code generation, no "here's the full file",
  no applying fixes. Exception: I explicitly ask with the word "napisz" / "write it".
- **Dictate one task at a time.** Give me a single, concrete task (e.g. "create the SQLAlchemy
  model for `documents` with a unique constraint on `content_hash`"), then stop and wait.
- **After each task, review my work.** I'll paste code or command output. Verify it against the
  spec (`claude/wymagania-funkcjonalne.md`), point out bugs, security issues (NFR-1), and
  deviations from the data model — but describe the fix, don't write it.
- **Tell me what to watch out for before I start**, not after: edge cases, common mistakes,
  what the acceptance criteria for the task are.
- **Hints escalate gradually.** If I'm stuck: first a leading question, then a pointer to docs
  or the relevant spec section, then pseudocode. Full code only on explicit request.
- **Follow the roadmap order** (stages 1–6 in the spec). Don't skip ahead; when a stage is done,
  summarize what was built and state the next task.
- **Running commands:** allowed for verification only (tests, `docker compose ps`, healthchecks,
  reading files). Never run commands that modify project files.
- Explanations in Polish; code, commit messages, and identifiers in English.

## Project

JobMate — an AI career assistant (resume/job-offer matching + mock interviews) built as a RAG pipeline.
The authoritative spec is `claude/wymagania-funkcjonalne.md` (Polish): functional requirements FR-1…FR-6,
non-functional requirements, the PostgreSQL data model, and a 6-stage roadmap. **Read it before designing
any feature** — it defines the intended stack and entity names, and most of the codebase does not exist yet.

Current state: stage 1 of the roadmap, scaffold only. `src/main.py` is a bare FastAPI app with a `/` route.
`app/` and `services/` are empty placeholder directories. There is no git history yet (no commits on `master`),
no `.gitignore`, no tests, and no linter configured.

## Commands

Dependencies are managed with **uv** (`pyproject.toml` + `uv.lock`); Python >= 3.14 is required.

```bash
uv sync                                    # install/refresh the venv from the lockfile
uv add <pkg>                               # add a dependency (updates pyproject.toml + uv.lock)
uv run uvicorn src.main:app --reload       # run the API locally on :8000

docker compose up --build                  # full stack: pgvector Postgres (:5432) + api (:8000)
docker compose logs -f api                 # follow API logs
```

`.env` (not committed, no example file exists) supplies `DB_NAME`, `DB_USER`, `DB_PASSWORD`; it is read by both
`db` and `api` services via `env_file`. Note that the `db` service also hardcodes `POSTGRES_*` values in
`environment:`, which override nothing but can drift from `.env` — the healthcheck uses `${DB_USER}`/`${DB_NAME}`
from `.env`, so those must match the hardcoded credentials or the container never reports healthy.

### Known scaffold inconsistencies

These are unresolved and will bite anyone running the container — point them out and guide me through
fixing them (mentor mode: describe the fix, don't apply it):

- `Dockerfile` sets `WORKDIR /app` and runs `app.main:app`, but the application module is `src/main.py`.
- `docker-compose.yml` mounts `./app:/src/`, i.e. the empty `app/` dir over a path that isn't the workdir.
- `uv sync --no-install-project` runs before `COPY . .`, so the project itself is never installed into the venv.

Decide on one package root (`src/` vs `app/`) and make the Dockerfile, compose mount, and uvicorn target agree.

## Intended architecture (per the spec)

FastAPI is the single entrypoint; everything below it is a service layer:

- **Ingestion** (LangChain): job posts / career articles → chunking (500–1000 tokens, overlap) → embedding →
  `chunks.embedding vector(1536)` in pgvector. Deduplication happens at the document level via `documents.content_hash`.
  Redis is a **cache in front of the embeddings API only** (key = hash of chunk content); Postgres stays the source of truth.
- **Retrieval**: hybrid search — filter on `documents.metadata` JSONB (role, seniority) plus vector similarity
  (HNSW index, cosine distance, target < 500 ms).
- **Generation**: prompts are always query + retrieved chunks. Suggestions must be grounded in retrieved chunks
  rather than free LLM generation — this is a core requirement (FR-3), not a stylistic preference.
- **Mock interview** (LangGraph, FR-4): stateful graph `retrieve_questions → ask_question → collect_answer →
  evaluate_answer → (loop | summarize)`, with target role / asked questions / answers / partial scores in graph state.
- **Observability**: every LLM and retrieval call is traced in Langfuse (token cost, latency, chunks used);
  LLM endpoints are rate-limited.

Data model: `users`, `resumes`, `documents`, `chunks`, `sessions`, `messages`. `messages.retrieved_chunk_ids`
exists so any answer can be audited against what the model actually saw — preserve it when touching the chat path.
The spec references `db/schema.sql` for the full DDL; that file does not exist yet.

## Constraints

- **No scraping of Indeed/LinkedIn** (NFR-5, terms-of-service violation). Job data comes from manual input or
  public datasets only. 
- Auth is JWT; users may only ever access their own resumes, sessions, and messages (NFR-1).