# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Working Principles

1. **Think before coding.** State assumptions explicitly; if uncertain, ask. Surface multiple interpretations instead of silently picking one. If a simpler alternative exists, say so before implementing.
2. **Simplicity first.** Minimum code that solves the problem. No speculative features, premature abstractions, or unrequested error handling.
3. **Surgical changes.** Touch only what you must. Don't refactor unbroken adjacent code. Match existing style. Clean up only your own mess.
4. **Goal-driven execution.** Turn vague requests into testable success criteria, then loop until verified (run tests, hit the endpoint, check output).

## Commands

```bash
source venv/bin/activate                      # required in every new terminal
docker-compose up -d                          # local PostgreSQL + pgvector
uvicorn app.main:app --reload --port 8000     # dev server → http://localhost:8000/docs

pytest                                        # all tests
pytest tests/search/test_semantic_pipeline.py # one file
pytest tests/search/test_semantic_pipeline.py::test_name  # one test

python -m app.db.seed --foods                 # sync foods JSON → DB
python -m app.db.seed --tags                  # sync tags/medical rules → DB

./deploy.sh                                   # build + deploy to Cloud Run (GCP)
./deploy.sh --sync-tags                       # deploy + sync tags_data.json
```

No linter/formatter is configured. No Alembic — tables are created on startup by `app/db/init_db.py`; schema changes mean editing models and recreating tables. See `docs/COMMANDS.md` for Cloud SQL proxy/logs commands.

## Architecture

FastAPI + async SQLAlchemy + PostgreSQL/pgvector. Gemini (google-genai) for intent extraction, embeddings (HALFVEC 3072 on `foods.embedding`), and explanations. JWT auth (stateless, MVP refresh). Images on Google Cloud Storage.

- `app/main.py` — app factory + lifespan (startup seed/sync controlled by env flags)
- `app/api/v1/router.py` — mounts all module routers
- `app/modules/<domain>/` — one package per domain (`auth`, `users`, `foods`, `search`, `chat`, `favorites`, `query_logs`, `admin`, `places`, `ingredients`), each with `router.py` / `service.py` / `models.py` / `schemas.py`
- `app/core/config.py` — all settings from `.env` (template: `.env.example`)
- `standard-data/` — source-of-truth JSON synced into DB: `tags_data.json` (medical/allergy rules), ingredient taxonomy, alias rules
- Root-level `main.py`, `models.py`, `schemas.py`, `database.py` are thin backward-compat shims — new code lives under `app/`

**No DB foreign keys** — relationships are managed in service code; don't add FK constraints casually.

### Search pipeline (the core of this repo)

`app/modules/search/service.py::search_food()` is the public facade. The env flag `SEARCH_PIPELINE_VERSION` (`legacy` | `semantic_first`, default `legacy`) switches between the old filter-first logic and the new pipeline in `app/modules/search/pipeline/`:

```text
orchestrator.py   coordinates the flow:
  1. intent.py       Gemini extracts ExtractedIntent from query + health profile (keyword fallback)
  2. retrieval.py    filter-free pgvector top-k by cosine similarity (lexical fallback)
  3. safety.py       hard filter: health conditions, allergies, excluded ingredients — absolute, never soft
  4. scoring.py      soft rerank: semantic score + preference/context bonuses − dislike penalties
  5. explanation.py  Gemini generates reasons for top results (must not reorder them)
types.py          ExtractedIntent, RetrievedFood, ScoredFood
```

Design intent (see `docs/semantic_first_search_refactor_plan.md`): retrieve semantically first, then apply only *critical* safety constraints as hard filters; preferences and dislikes only affect ranking, never eliminate. Every search persists a trace to `query_logs.excluded_summary` (retrieval/safety/scoring decisions) — keep this trace intact when changing the pipeline.

### Medical rules & ingredient keys

Tags in `tags_data.json` carry `exclude_ingredient` / `prefer_ingredient` / `exclude_soft_tag` / `prefer_soft_tag` rules, matched against normalized ingredient keys (`base:*` / `canon:*` / `group:*`) produced by `app/modules/ingredients/`. Safety filtering and scoring both depend on this key system — changing alias rules affects allergy matching.

### Chat

`app/modules/chat/` classifies message intent and dispatches to handlers (new_search, food_info, food_safety_check, location_search, follow_up); food queries reuse `search_food()` with the thread's accumulated context.

## Notes

- README.md and docs/ are in Vietnamese; respond to the user in their language.
- `docs/PROJECT_MEMORY.md` and `docs/DEPLOY_LESSONS.md` record past decisions and deployment pitfalls — check before redoing work.
