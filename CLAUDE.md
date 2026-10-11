# CLAUDE.md

## Project Context

This is the **PlateMates** project: a web application for the weekly menu and the shopping list
of people who eat together (a **team**: a family, a person living alone, flatmates, friends, a
sports team, an office), driven by an LLM that acts in an agentic way. For the full purpose and
the conceptual model (team, menu, recipe, ingredient catalog), see `README.md`.

The product name is **PlateMates** (it was "WeeklyMenu", and "Family Menu Planner" before), and
technical identifiers follow it (`platemates` realm, theme, Compose project, volume, database).
`WeeklyMenu` in the code is the model of a week's menu, not the product: never rename it.

"Team" is the product's word and the code's (`Team`, `/api/teams/`); it was "family" until
2026-10-07. The Django app keeps its original label `families` and table prefix (see
`docs/architecture.md`); never rename them.

The functional and architectural design was defined in a planning session with the user (Paolo). This document guides operational development in Claude Code.

## Project Status

**Recipe book, menu generation and shopping lists built.** Built and in use: recipe book and editor, the recipe
assistant in all four modes (tell, link, photo, search), sign-in with invitation-only teams,
team management, the team calendar and menu screen, the menu planning rules (system, team,
week), weekly menu generation with review, the management section for shared catalogs, phone
access over HTTPS on the home network, backups, shopping lists (generated per week, merged,
ticked live). Not built yet: tastes,
feedback, collaborative recommendation. The README's status table is kept current;
`docs/architecture.md` explains how the code maps onto the concepts and the decisions taken.

## Technology Stack

- **Backend**: Python, **Django** + Django REST Framework
  - Reasons: robust ORM for a highly relational data model (teams, recipes, ingredients, menus), app-based structure (recipe book, menu/teams, LLM integration), free admin panel
- **Authentication**: **Keycloak** (email/password, Google, Microsoft, Apple) with Django as OIDC
  client and session cookies; invitation-only access. See `docs/authentication.md`
- **Frontend**: **React** (SPA), decoupled from the backend via REST API
  - Possible future wrapping in **Tauri** for a desktop version with local storage, same codebase
- **Database**: **PostgreSQL** as the single database
  - **pgvector** for embeddings (chosen over a dedicated vector DB such as Qdrant for operational simplicity: one DB to manage and deploy, direct joins between relational and vector data; the expected scale does not justify a separate system)
  - **JSONB** for any semi-structured fields
  - No Elasticsearch or CouchDB/Couchbase: at this scale, PostgreSQL's full-text indexes and vector search are enough
- **Local generative LLM**: **Unsloth Studio** on the host (`http://127.0.0.1:8888`), as in Paolo's
  `spyone` project (`../spyone`); default model `unsloth/Qwen3.6-35B-A3B-MTP-GGUF`
- **Embeddings**: **swappable** component behind a stable interface (OpenAI-compatible style)
  - Starting point: local open-source model (sentence-transformers, multilingual)
  - Open alternative: cloud API (e.g. Google Cloud) if quality justifies it; usage is occasional (only on new recipes/ingredients), so cost would be negligible
  - Write an adapter for the chosen provider; do not hardcode it
- **Recipe discovery**: native web search capability of the LLM (no dedicated scraping at this stage).
  Importing a single page whose link the user gives is allowed: schema.org Recipe data first,
  LLM extraction as fallback; no crawling, no per-site scrapers
- **Deployment**: **Docker Compose**, portable between a local ARM64 Mac, a home Raspberry Pi, and a cloud VM. No "all-in-one" packaging

## Architecture

- The Django backend exposes REST APIs consumed by the React frontend
- The generative LLM and the embedding component are **decoupled services**, reached by the backend through stable OpenAI-compatible-style interfaces, swappable without touching application logic
- Relational data (recipes, ingredients, teams, menus, feedback) and vector data (recipe and team-profile embeddings) coexist in PostgreSQL
- The menu generation engine is agentic and uses **RAG** logic: it retrieves structured data and vector similarity results and passes them as context to the LLM. Feedback informs the context; it is **not** used for fine-tuning
- Two levels of vector similarity: between recipes (variety and discovery) and between team profiles (collaborative recommendation)
- Shopping list: in the first version it is a pure output generated from the menu; offline use on mobile is delegated to a possible integration with an existing app (API/MCP)

## Development Guiding Principles

- **Parametricity**: no team data (people, ages, tastes, tools) hardcoded
- **Multi-team from the data model**: even with a single real user at the start, the schema must not assume a single team
- **People per slot**: the number of people is an attribute of each meal in the menu (default 2 at lunch, 3 at dinner, overridable, even 0), not of the team
- **Responsive web interface**: desktop-first, mobile-ready in design
- **Proactive LLM, not just reactive**: the engine actively proposes variety, including recipes not yet in the recipe book
- **The user always has the final say**: every property derived or suggested by the LLM (seasonality, tags, cuisine, etc.) is editable and confirmable by the user, at recipe level or single-ingredient level
- **Swappable LLM/embedding components**: never tie application logic to a specific provider
- **Optional feedback**: the implicit signal (menu followed / what was actually eaten) is the baseline; explicit rating is optional

## Reference Features

Full detail in `README.md`:

1. Structured recipe book (normalized ingredients, two-level seasonality, cuisine type, times, ratings)
2. Parametric team profile
3. Weekly menu generation engine (agentic, proactive)
4. Shopping list generation
5. New recipe discovery
6. Kitchen tool inventory
7. Feedback and learning (implicit + explicit, via RAG)
8. Collaborative recommendation between teams

## Working Conventions for Claude Code

### Layout

- `backend/`: Django project (`config/`), domain apps in `apps/` (`accounts`, `catalog`,
  `recipes`, `teams`, `menus`, `assistant`, `siteconfig`, `curation`, `transfer` (export and
  import between installations), `usage` (AI consumption by team); `core` holds abstract mixins and the
  cache manager), AI
  adapters in `ai/`, tests in `tests/`
- `frontend/`: React + TypeScript (Vite) with **MUI 9** (theme in `src/theme.ts`);
  `src/api.ts` is the only place that calls `fetch`; enum labels live in `src/labels.ts`
- `backend/apps/realtime/`: the Socket.IO service (`realtime` in compose) at `/websocket/`
- `services/embeddings/`: standalone OpenAI-compatible embedding server
- `keycloak/`: Keycloak image (login theme, Apple provider)
- `scripts/`: repository-level tooling (`init_env.py`, `backup.py`, `setup_lan_https.py`,
  `deploy.sh`)
- `monitoring/`: VictoriaMetrics scrape config, Grafana provisioning, dashboards and alerts
  (generated by `monitoring/grafana/make_dashboards.py` and `make_alerts.py`: change the
  generators, not the JSON), read-only DB roles
- `traefik-admin/`: the admin plane's routes (served only on the server's loopback)
- `deploy/`: Ansible for the public server (inventory, roles `base`, `docker`, `backup`, `monitoring`,
  `platemates`);
  `docker-compose.prod.yml` is the server's overlay; `.github/workflows/images.yml` tests and
  publishes the images
- `docs/architecture.md`: design decisions; update it when you change one
- `docs/authentication.md`: login flow, invitations, provider setup
- `docs/operations.md`: where data lives, backup/restore, moving to another machine, the public
  server

### Environment

- Python 3.12 managed with **uv** in `backend/` and `services/embeddings/` (`uv run`, `uv add`);
  never call pip directly. If a stale `VIRTUAL_ENV` from pyenv is set, `export VIRTUAL_ENV=`
  silences uv's warning
- Node 24, npm in `frontend/`
- Configuration only from the root `.env` (template: `.env.example`); never commit `.env`.
  `python3 scripts/init_env.py` creates or completes it (generates missing secrets, adds new
  keys, never overwrites a value)
- PostgreSQL is the only supported database, also for tests: start it with
  `docker compose up -d db`. Redis is the cache (`docker compose up -d redis`); tests use
  in-memory caches instead (`tests/conftest.py`)
- Signing in needs Keycloak running and configured: `docker compose up -d db keycloak`, then
  `uv run python manage.py setup_keycloak`. Use the app through the SPA's origin (`:5173` or
  `:8080`, or `:8443` over HTTPS from other devices), never directly on `:8000`: Keycloak is
  served under `/auth` on that same origin, and only accepts those as redirect targets

### Commands

```bash
python3 scripts/init_env.py                             # create/complete .env (idempotent)
docker compose up -d db keycloak redis                  # database, identity provider, cache, for native development
cd backend && uv run python manage.py setup_keycloak    # configure the Keycloak realm from .env (idempotent)
cd backend && uv run python manage.py create_team "Name" --owner you@example.com --staff  # bootstrap
cd backend && uv run python manage.py migrate           # apply migrations
cd backend && uv run python manage.py runserver         # API on :8000, admin on /admin/
cd backend && uv run python manage.py worker            # menu generations and system recipe drafts (`worker` in compose)
cd backend && uv run uvicorn apps.realtime.asgi:app --port 8001 --ws wsproto   # Socket.IO at /websocket/ (`realtime`)
cd backend && uv run pytest                             # backend tests (needs the db running)
cd backend && uv run ruff check --fix . && uv run ruff format .
cd services/embeddings && uv run uvicorn app.main:app --port 8100   # local embeddings
cd services/embeddings && uv run pytest
cd frontend && npm run dev                              # SPA on :5173, proxies /api to :8000
cd frontend && npm run build && npm run lint
docker compose up -d --build                            # full stack on :8080
cd backend && uv run python manage.py embed_recipes     # (re)compute missing or stale recipe embeddings
python3 scripts/setup_lan_https.py                      # HTTPS on the home network (phones), see docs/operations.md
scripts/deploy.sh                                       # deploy to the public server (Ansible in Docker)
python3 scripts/backup.py create                        # back up both databases + .env to backups/
python3 scripts/backup.py restore backups/<file>.tar    # replace all data (takes a safety backup first)
```

### Rules

- Every property the LLM suggests or the code derives goes through `ProvenanceMixin.propose`;
  never assign it directly. API writes are user decisions and are marked as such automatically
- Staff and administrator powers exist only on the admin plane: every check goes through
  `apps.core.planes.staff_powers` / `admin_powers`, never `user.is_staff`, `IsAdminUser` or the
  profile's `is_admin` directly. Anything administrative is routed only by the admin Traefik
  (`traefik-admin/dynamic.yml`, loopback only), never by the public one
- Team-owned data is reached only through `TeamScopedMixin` querysets: a user never sees
  another team's data. Writes that change the team itself (profile, people, roles, invitations)
  go through `OwnerWritesMixin` / `require_owner`
- Application logic talks to AI only through `ai.get_chat_provider()` /
  `ai.get_embedding_provider()`; provider-specific code lives in `ai/` only
- Embeddings are always stored with the model name that produced them
- AI calls are billed to a team and feature: a new place that starts AI work wraps it in
  `apps.usage.context.attribute(...)`, and work handed to threads goes through `carry()`;
  providers report usage through `ai.usage.report`
- Unsloth Studio's server-side tools are enabled only through `StudioChat`, which restricts them
  to `web_search` and caps tool calls: never send `enable_tools` with Studio's other tools
  (`python`, `terminal`, `edit_file` run on the host)
- The backend fetches user-given URLs only through `apps.assistant.web.fetch`, which refuses
  non-public addresses at every redirect: never fetch a user-supplied URL with a bare httpx call
- An assistant mode is enabled (`AVAILABLE_MODES`) only once its tools exist: the LLM must never
  be asked about a page, photo or search result it cannot actually read
- Menu generation is guided only by the rules (`SystemRule`, `TeamRule`,
  the week's settings on `WeeklyMenu`) plus the structured team data; `Team.notes` is a note for
  users and is never passed to the LLM. Hard constraints are enforced in code, not in rule text
- Settings that tune behaviour at runtime are `ConfigVar`s defined in
  `apps/siteconfig/registry.py` and read with `registry.get`, changed only by administrators;
  `.env` is for the deployment (addresses, secrets). Never hardcode a budget tied to the model's
  context: derive it from `llm.context_tokens`
- Data read often and changed rarely (rules, settings) is read through
  `apps.core.cache.cache_manager`, never at start-up; its models clear the cache from their
  signals, so write them with `save()` / `delete()`, never a bulk `update()`
- Real-time events (`apps.realtime.events.publish`) are notices to a team's browsers, never the
  only way state reaches them: every screen that listens also reloads from the API on
  (re)connection. Never send data a user of another team must not see: rooms are per team
- The administrator role comes only from `APP_ADMINS` through `setup_keycloak`, and reaches the
  app as the ID token's `roles` claim; never grant it by hand or decide it in Django
- Whatever the menu generator returns is a proposal (`SlotDish.proposed`,
  `MealSlot.proposed_people`) validated in `apps/menus/generation.py`, and counts only once the
  user accepts it (`apps/menus/review.py`). The generator never writes the calendar; people
  change only through `set_day`
- A shopping list is a snapshot of the menu when it was generated: it never follows later menu
  changes. Every change to a list or its items is announced with `announce` (`shopping` event)
- Everything the assistant produces goes through `normalize_draft` and the editor's review;
  nothing it proposes is saved without the user
- **Every initialization step must be idempotent** (safe to re-run, same result) and, where it
  mirrors configuration, convergent (re-running after a config change applies the change).
  Today: `init_env.py`, migrations and seed data (ingredients, kitchen tools, system rules:
  never overwriting what users changed), `db-init`, `setup_keycloak`, `create_team`.
  Verify a new step by running it twice
- On the public server, the database archives its WAL into pgBackRest's repository
  (`/var/backups/platemates`): never turn archiving off, never touch the repository by hand, and
  keep the pgBackRest passphrase (vault) safe: without it no backup can be read
- Never run `docker compose down -v` (or remove `platemates_pgdata`) without a fresh backup: it deletes
  both databases, Keycloak accounts included. `backups/` holds personal data: never commit it
- The public server is changed only through `scripts/deploy.sh` (Ansible, `deploy/`), never by
  hand, and runs only images built by GitHub Actions. Its secrets are generated on the server and
  never leave it; personal values go in the ansible-vault file, never in plain text (the
  repository is public)
- Keycloak is configured only through `setup_keycloak` (from `.env`), never by hand in its console
- Routing lives in Traefik labels on each service in `docker-compose.yml`, one router per entry
  point (`web`, and `websecure` with `tls=true`); the `frontend` container only serves files
- Keycloak has no fixed hostname and lives under `/auth` on the app's origin: never hardcode a
  Keycloak URL that the browser follows; browser-facing OIDC endpoints stay relative
- The interface language and the theme (light, dark, or following the device) are per-user
  preferences saved in the backend, not only in the browser
- Users are matched on the OIDC `sub` claim, never on email; no OIDC token is ever sent to the
  browser
- No dependency that requires CUDA: the stack must run on a Raspberry Pi
- MUI 9 no longer accepts style props on components (`alignItems`, `fontWeight`, ...): put
  them in `sx`. Colours come from the theme (`theme.vars` for anything outside `sx`), never
  hardcoded, so light and dark both work
- UI strings go through i18next (`frontend/src/i18n/locales/{it,en}.json`), Italian default; add
  every new key to both files. Backend labels use `gettext_lazy`
- Ingredients are system ones (`owner_team` null, staff-curated) or a team's own: what a team
  may pick, match or use in a recipe or preference is `Ingredient.objects.usable_by(team)`, and
  system recipes use system ingredients only. Never let a team see or pick another team's
  ingredients
- Seasonality is stored as months; season mode is only a view (see `docs/architecture.md`)
- Preserved products ("pomodoro pelato", "passata di pomodoro") are distinct ingredients from
  the fresh one, available all year; never fold them into the fresh product
- Catalog entries the app ships with (kitchen tools) have a stable `code` and are translated in
  the UI; never show their stored English name to users. User-added entries have no code
- The system team (`Team.is_system`, "PlateMates") owns the curated community recipes: it has
  no members, only staff write its recipes, and they are always shared. Whether a team's
  recipe is shared is the user's choice at creation: never give `visibility` a default in the
  API or the editor
- System recipe drafts (`apps/curation`) never become recipes by themselves: staff publish them
  from the recipe editor (`system_draft` on create). Their ratings are computed from the
  verified source pages, never asked of the model
- Data moves between installations through `apps/transfer` (export/import by stable `uid`,
  catalogs matched by name too), never by copying database ids. A model whose objects travel in
  export files has a `uid`; add new fields to `exporting.py` and `importing.py` together
- Tests use synthetic data, never real team data
- Commit messages: imperative summary line, English; one logical change per commit

## Cross-References

- Unsloth Studio: `../spyone/CLAUDE.md` and `../spyone/docs/architecture.md` (verified endpoints,
  auth, model loading); the parts relevant here are summarized in `docs/architecture.md`
