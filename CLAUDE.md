# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working mode — mentor, not implementer

**I (Bartek) write all the code myself. Claude Code acts as a mentor and never implements for me.**

Rules:
- **Never write, edit, or create project files.** No code generation, no "here's the full file",
  no applying fixes. Exception: I explicitly ask with "napisz" / "write it" / "wykonaj za mnie" /
  "wprowadź zmiany" — then implement that one thing, not the rest of the stage.
- **Dictate one task at a time.** Give me a single, concrete task (e.g. "add an admin-only dependency
  and `DELETE /documents/{id}`"), then stop and wait.
- **After each task, review my work.** I'll paste code or command output. Verify it against the
  spec (`claude/wymagania-funkcjonalne.md`), point out bugs, security issues (NFR-1), and
  deviations from the data model — but describe the fix, don't write it.
- **Tell me what to watch out for before I start**, not after: edge cases, common mistakes,
  what the acceptance criteria for the task are.
- **Hints escalate gradually.** If I'm stuck: first a leading question, then a pointer to docs
  or the relevant spec section, then pseudocode. Full code only on explicit request.
- **Follow the roadmap order** (spec §7). Don't skip ahead; when a stage is done,
  summarize what was built and state the next task.
- **Running commands:** allowed for verification only (tests, linters, `docker compose ps`,
  healthchecks, reading files). Never run commands that modify project files.
- Explanations in Polish; code, commit messages, and identifiers in English.

## Project

JobMate — an AI career assistant: store job postings, match a resume against one, get grounded suggestions,
and practise a mock interview on it.
The authoritative spec is `claude/wymagania-funkcjonalne.md` (Polish): FR-1…FR-6, NFR-1…NFR-5, the data model,
the roadmap, and dated **"Zmiana"** entries that record every change of direction with its reason. **Read it
before designing any feature**, and read §8 ("Pułapki, których nie widać z kodu") before touching scraping,
migrations, ingestion or tokens — that section is the only record of traps that were stripped from code comments.

### Current state (2026-09-26)

- **Done:** stages 1–5 — the whole MVP roadmap.
  - 1–3: auth (JWT via Bearer header or httpOnly cookies), resumes (text or file upload), job-posting
    ingestion (pasted text, PDF/DOCX/TXT upload, or URL from an allowlisted host), chunking + embeddings with
    a Redis cache, requirement-by-requirement matching with stored match history, a React client in `web/`,
    Langfuse tracing and prompt store, rate limiting, offline evals in `evals/`.
  - 5 (PRs #5–#12): FR-6 — admins delete postings (`DELETE /documents/{id}`, a button on the postings list),
    `scripts.grant_admin` grants the rights, `scripts.reindex` re-embeds after a model change. FR-5 — a stored
    resume exports as Markdown, Word or PDF, with download buttons on the Resumes page.
  - 4 (PRs #13–#20): FR-4 — a mock interview on one posting for one resume: questions planned up front from
    the posting's `requirements` (gaps first), each answer judged by a rubric with a tip, a summary at the end,
    and a history of sessions. API under `/sessions`; started from a posting's page, a posting row, or
    `/interview`. Decisions D-1…D-5 are at FR-4 in the spec; the design is
    `docs/superpowers/specs/2026-09-24-stage4-mock-interview-design.md`.
  - Frontend redesign (PRs #24–#40), aimed at everyday use, in four parts with a design doc each
    (`docs/superpowers/specs/2026-09-24-ui-*-design.md`): **foundation** (warm palette, light/system/dark
    toggle, Nunito Sans, lucide icons, restyled `ui/`), **navigation** (a page per posting at
    `/documents/:id` as the centre of the work, one `/history` for matches and interviews, API
    `GET /documents/{id}` and a `document_id` filter), **states** (skeletons, empty states, "Try again",
    `Thinking` for model waits, neutral `Notice`), **hierarchy** (postings as rows with Match/Practise,
    the main resume first, interview progress and summary on top). Match and Interview were removed from
    the nav in part 2 and brought back on request. The look of part 1 was replaced by the visual identity
    below; parts 2–4 stand.
  - Dashboard (PR #45): the home page `/` answers "what next" — one step in a sentence with its action
    (add a resume or posting, continue an interview, match, practise), the other steps under it, and recent
    work. Steps come from `GET /dashboard`. Decisions DB-1…DB-6 are in
    `docs/superpowers/specs/2026-09-26-dashboard-design.md`. The nav is Home, Postings, Resumes, Match,
    Interview, History.
  - Visual identity "recruitment file" (PR #46): Public Sans, cool paper and navy ink, a stamp red kept for
    gaps; a posting is drawn as a file with a tab, and how far you got with it as a path of four stages
    (Posting, Match, Interview, Applied — the last dashed until it exists). API: `stage` and `best_score` on
    each posting, for the caller. Decisions V-1…V-7 in `docs/superpowers/specs/2026-09-26-ui-identity-design.md`.
- **Next:** nothing scheduled. Two candidates, ask before starting either: tracking sent applications
  ("Applied" — a per-user table, since postings are shared; its stage slot is already drawn), and stage 6
  (bonus: voice, salary trends).
- **Removed:** FR-7 automated harvesting (Scrapy) — built and reverted on 2026-09-10; the spec says why.
  Don't reintroduce crawling: NFR-5 allows one fetch per explicit user action, nothing more.

## Layout

- `app/` — FastAPI package (`app.main:app`). `api/` routers + `deps.py` (DI, auth, rate limits, ownership
  checks like `OwnedResume`), `auth/`, `core/` (config, db, redis, Langfuse, prompts), `models/`, `schemas/`,
  `services/` (chunking, embeddings, extraction, ingestion, jobposting, scraping, requirements, judging,
  matching, rate_limit, reindexing, export, dashboard, stages; interview: `interview_graph` the LangGraph graph, `interviewing`
  the model calls, `interview` the service that joins them to the database), `assets/fonts/` (PT Sans + its OFL licence, for PDF export).
- `migrations/` — Alembic; the only source of truth for the schema (no `db/schema.sql`).
- `web/` — React + TypeScript (Vite) client. Types in `web/src/api/schema.d.ts` are generated from
  `web/openapi.json`, which is generated from the app. `src/ui/` holds every shared component behind one
  `index.ts` (controls incl. `ButtonLink` for a link drawn as a button; surfaces incl. `Sheet`, with an
  optional file `tab`; data incl. `Chip`, `Score`, `percentage`; `StageRail` and `reachedOf`; feedback; the
  theme toggle); `src/theme.ts` the theme choice; `src/time.ts` relative dates; `src/routes/` one file per
  screen (`Dashboard` is `/`; `PairPicker` backs Match and Interview; `timeline.ts` and `TimelineItem.tsx`
  are the history rows History and the dashboard share).
- `scripts/` — a package, run as `python -m scripts.<name>`: `export_openapi`, `seed_prompts` (Langfuse),
  `eval_*` runners for `evals/`, `grant_admin` and `reindex` (FR-6).
- `docs/superpowers/specs/` — per-stage design docs.

## Commands

Dependencies are managed with **uv**; Python >= 3.14. Locally the API runs in Docker only (Linux); tests run
on the host against the compose Postgres/Redis.

```bash
docker compose up --build                  # db (pgvector), redis, api :8000, web :5173, Langfuse :3000
docker compose --profile prod up --build web-prod   # nginx + built client on :8080
docker compose logs -f api

uv sync                                    # host venv (tests, linters, scripts)
uv run alembic upgrade head                # apply migrations
uv run alembic check                       # models match migrations (CI runs this)
uv run pytest -q                           # all tests; single: uv run pytest tests/test_matching.py -k name

cd web && npm run gen                      # regenerate openapi.json + schema.d.ts after any API schema change
cd web && npm run lint && npm run typecheck && npm test

# Admin tools run inside the api container; scripts/ is baked into the image, so --build after changing one
docker compose exec api python -m scripts.grant_admin someone@example.com [--revoke]
docker compose exec api python -m scripts.reindex --dry-run   # count + token estimate; drop the flag to pay
docker compose exec api python -m scripts.seed_prompts        # TEMPLATES -> Langfuse production; overrides edits made there
```

`.env` (from `.env.example`) configures the API; `Settings` uses `extra="forbid"`, so an unknown key in `.env`
aborts startup. Langfuse's own config lives in `.env.langfuse` for exactly that reason — never merge them.

### Verification — what "green" means here

Run all of these over the tree before claiming anything passes:

```bash
uv run pytest -q
uv run ruff check . && uv run ruff format --check .
uv run mypy                                # bare: pyproject covers app, migrations, scripts, tests, ui
uv run bandit -c pyproject.toml -r app migrations scripts
uv run pre-commit run --all-files          # last, not only: skips untracked files
```

CI (`.github/workflows/ci.yml`) has two jobs. Python: pre-commit, OpenAPI drift check, migrations,
`alembic check`, pytest. Node: `schema.d.ts` drift check, lint, typecheck, vitest, build. **Any change to a
Pydantic schema or route must regenerate `web/openapi.json` and `web/src/api/schema.d.ts`**, or both jobs fail.

## Architecture notes

- **Knowledge base = job postings only** (since 2026-09-02). Ingestion dedups on the unique index on
  `documents.content_hash` (catching `IntegrityError`, not select-then-insert) and commits on its own.
  Requirements are extracted by an LLM at write time into `documents.requirements`.
- **Matching (FR-3) does not use vector retrieval.** A deterministic rule matches skills first; an LLM judge
  may only *add* matches, requirement by requirement, quoting the resume. Score and gaps are computed in Python
  from the verdicts. Suggestions must be grounded in the posting + resume — never invent employers, dates,
  technologies or achievements. Every match is stored in `matches` (a snapshot; FKs go NULL on delete).
- **Mock interview (FR-4)** follows the same rule as matching: the model words questions and judges answers,
  Python decides. The plan is fixed at the start (one question per requirement — a plan that doesn't echo
  the requirements back in order is refused, not repaired); the evaluator returns yes/no verdicts per
  criterion in `CRITERIA` and the score is the share met; the summary calls no model. The graph never
  touches the database and has no checkpointer: `app/services/interview.py` rebuilds its state from
  `sessions`/`messages` each turn, runs one turn and writes it in one transaction under a row lock, so a
  model failure (→ 502) saves nothing. Progress is derived from the messages, not a counter; order is
  `position`, not `created_at`. An answer names the question it answers (`question_id`), else a double
  submit would be taken as the answer to the next question (→ 409). The planner's tokens and chunk ids ride
  on the first question. Structured outputs reject objects with arbitrary keys, so the evaluator answers a
  list that `to_rubric` turns into the dict the graph uses.
- Embeddings + HNSW index are still written and maintained, but nothing reads them — stage 4 doesn't either
  (its questions come from `requirements`), so NFR-3 is suspended until some feature searches. Each chunk records
  `embedding_model` (NULL = older than the column = unknown). Re-indexing selects stale chunks with
  `IS DISTINCT FROM`, never `!=` (which skips NULL), and updates vectors **in place** so chunk ids — and
  `retrieved_chunk_ids` pointing at them — survive; one commit per document, so a failed run just resumes.
- **Admin (FR-6):** `CurrentAdmin` in `app/api/deps.py` answers 403 after authentication (401 stays with
  `get_current_user`). No route grants `is_admin`, on purpose — only `scripts.grant_admin`. The flag is read
  from the database on every request, so a grant or revoke applies to tokens already issued.
- **Export (FR-5):** converts a stored resume version and calls no model — the "improved" resume is one its
  owner wrote. The filename is always `resume-<id>.<format>`, never user text (it lands in
  `Content-Disposition`). PDF uses fpdf2 with the bundled font (the core PDF fonts are Latin-1 only) and drops
  characters the font lacks. The browser downloads through the API client, not a plain link, because only the
  client renews an expired access cookie.
- **Dashboard:** Python chooses the steps (`app/services/dashboard.py`), one query per rule, because "a
  posting you haven't matched" and "your best match without an interview" are questions about every row and
  the client's lists are paged. Postings are shared but matches, sessions and resumes are filtered by user
  (NFR-1). A step needs its posting and resume to still exist — answers are judged against the resume. The
  list is never empty. In the client, **every mutation of resumes, postings, matches or interviews must
  invalidate `dashboardKey`**, or going back to `/` shows a step already done.
- **Prompts** are served from Langfuse with a code fallback (`app/core/prompts.py`); every LLM call is traced.
- **URL ingestion** reads only the `application/ld+json` `JobPosting` block from hosts in
  `SCRAPER_ALLOWED_HOSTS` (exact match, redirects validated per hop, body capped after decompression).
- **Browser and API share one origin** (Vite/nginx proxy `/api`). Cookie auth relies on `SameSite=Lax` —
  splitting origins needs a real CSRF answer, not looser cookies. `COOKIE_PATH_PREFIX` must match the proxy.
- **Web client conventions.** Colours are CSS variables in `styles.css` (`:root`, `[data-theme="dark"]` and
  the system media query) that `@theme inline` points Tailwind at; every text/background pair has its
  measured contrast in a comment, and a new colour is measured before it lands (text 4.5:1, control borders
  3:1 via `--control`). The theme is applied before first paint by a few lines in `index.html` that mirror
  `theme.ts` — change one, change both. States follow one vocabulary: `Skeleton` while loading, `EmptyState`
  with a way forward, `Alert` only for what failed (with `onRetry` for failed reads), `Notice` for hints,
  `Thinking` for waits of seconds, `Status` for a success. Tests find elements by role and label; a restyle
  that breaks one changed behaviour. "Main resume" means the newest (`newest()` in `routes/Posting.tsx`).
- **Visual identity conventions.** Sheets are told from the page by a line, never a shadow; `rounded-card`
  (6px) for sheets, `rounded-control` (4px) for buttons, chips and fields — no pills. Section headings are
  plain sentences (no uppercase labels); metadata is a sentence with commas, never "A · B · C"; times are
  `ago()` with the full date in `title`. A missing requirement is `Chip present={false}` (the stamp); where
  met and missing share one list, add words for a screen reader, since no heading separates them. A
  posting's `stage`/`best_score` are the caller's, so **matching and starting an interview must invalidate
  `documentsKey`** as well as the dashboard. A dependency added to `web/` needs
  `docker compose up -d --build --renew-anon-volumes web`: the container's `node_modules` is its own volume.

## Constraints

- **No scraping of Indeed/LinkedIn, no crawling anywhere** (NFR-5). Adding a host to the allowlist is a
  documented decision (robots.txt + terms checked), not a code change.
- Auth is JWT; users may only ever access their own resumes, matches, sessions, and messages (NFR-1).
- `messages.retrieved_chunk_ids` / `matches.retrieved_chunk_ids` exist for auditing what the model saw —
  preserve them when touching those paths.
