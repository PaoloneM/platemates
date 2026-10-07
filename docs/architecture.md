# Architecture

How the concepts in `README.md` map onto code. Read this before changing the data model or the AI
integration.

## Components

```mermaid
flowchart LR
    user["Browser or phone"]

    subgraph compose["Docker Compose (project mymenu)"]
        traefik["traefik<br/>entry point, routing from labels<br/>:80 = Mac :8080, :443 = LAN :8443"]
        spa["frontend<br/>nginx serving the built SPA"]
        backend["backend<br/>Django + DRF, gunicorn"]
        keycloak["keycloak<br/>/auth, theme mymenu"]
        db[("db<br/>PostgreSQL 17 + pgvector<br/>databases mymenu, keycloak")]
        embeddings["embeddings<br/>FastAPI + sentence-transformers"]
        jobs["one-shot jobs<br/>db-init, keycloak-setup, embed-recipes"]
    end

    subgraph host["Host machine"]
        studio["Unsloth Studio :8888<br/>chat, vision, web search"]
    end

    web[("Public recipe websites")]
    idp["Google, Microsoft, Apple"]

    user --> traefik
    traefik -- "/" --> spa
    traefik -- "/api /oidc /admin /static" --> backend
    traefik -- "/auth (admin console refused)" --> keycloak
    backend -- "OIDC code exchange, keys" --> keycloak
    backend --> db
    keycloak --> db
    backend -- "OpenAI-compatible chat" --> studio
    backend -- "/v1/embeddings" --> embeddings
    backend -- "link import and result checks,<br/>public addresses only" --> web
    studio -- "web_search tool" --> web
    keycloak -. "identity brokering" .-> idp
    jobs -.-> db
    jobs -.-> keycloak
    jobs -.-> embeddings
```

| Directory | What | Runs as |
|---|---|---|
| `backend/` | Django project `config`, domain apps in `apps/`, AI adapters in `ai/` | `backend` container, or `uv run` natively |
| `frontend/` | React + TypeScript SPA (Vite) | `frontend` container (nginx, static files only), or `npm run dev` |
| `services/embeddings/` | OpenAI-compatible `/v1/embeddings` around sentence-transformers | `embeddings` container, or `uv run uvicorn` |
| `keycloak/` | Keycloak image: login theme `mymenu` + Apple provider extension, served under `/auth` | `keycloak` container; realm configured by `keycloak-setup` |

The frontend and backend always share one origin (Vite proxy in development, Traefik in the
stack), so the API uses Django session auth and CSRF without CORS. Both proxies must keep the
original `Host` header: Django builds the OIDC callback URL from it, Keycloak its own URLs.

**Traefik is the entry point** (decided 2026-10-07, replacing nginx as reverse proxy): routing
is declared as labels next to each service in `docker-compose.yml` (`/api /oidc /admin /static`
to the backend, `/auth` to Keycloak, the rest to the SPA; Traefik tries longer rules first), and
it follows containers as they are recreated, which nginx needed a DNS workaround for. Each route
has two routers, one per entry point (`web` plain HTTP, `websecure` TLS), because a Traefik
router either requires TLS or not. Keycloak's admin console is refused with an IP allow-list
nobody matches (Traefik has no deny middleware). The LAN certificate comes from the file
provider (`secrets/tls/tls.yml`, written by `scripts/setup_lan_https.py`) and is reloaded
without a restart; Let's Encrypt can be enabled the same way once the app has a public domain.
Traefik does not serve files, so the SPA stays in a small nginx container that only serves the
build. Traefik reads the Docker socket read-only to discover containers; on a machine exposed to
the internet, put a socket proxy in between (`docs/operations.md`).

**Authentication** is Keycloak (email/password, Google, Microsoft, Apple) with Django as OIDC
client, and access is invitation-only. Full design and setup: `docs/authentication.md`.

## Domain apps

| App | Models | Notes |
|---|---|---|
| `catalog` | `Ingredient`, `KitchenTool` | Global, shared by every team. Ingredient names are normalized on save (lowercase, single spaces); variants go in `aliases`. |
| `recipes` | `Cuisine`, `Recipe`, `RecipeIngredient`, `RecipeEmbedding` | Recipes live in one common pool; quantities refer to `Recipe.servings` and scale linearly. The method is `Recipe.steps`, one entry per step. |
| `teams` | `Team`, `Membership`, `Member`, `Preference`, `RecipeBookEntry`, `TeamEmbedding` | Everything team-specific. `RecipeBookEntry` is the per-team view of a recipe: candidate / approved / rejected, plus the explicit rating. |
| `menus` | `WeeklyMenu`, `MealSlot`, `SlotDish` | 7 days × {lunch, dinner}. Shopping list in `menus/shopping.py`, computed, never stored. |
| `accounts` | `OIDCIdentity`, `Invitation` | OIDC backend and login view (`oidc.py`), Keycloak realm setup (`keycloak_admin.py`), `/api/me/`, invitations. |
| `assistant` | `AssistantSession` | The recipe assistant: conversation turns (`agent.py`), the recipe draft shape shared by every mode (`draft.py`). |
| `core` | none (abstract mixins and helpers) | Seasonality and provenance helpers, shared serializer mixin. |

### Data model

```mermaid
erDiagram
    USER ||--o{ MEMBERSHIP : "belongs to teams through"
    TEAM ||--o{ MEMBERSHIP : "has"
    TEAM ||--o{ MEMBER : "eats with"
    TEAM ||--o{ PREFERENCE : "states"
    INGREDIENT ||--o{ PREFERENCE : "about"
    TEAM }o--o{ KITCHEN_TOOL : "owns"
    TEAM ||--o{ RECIPE : "owns"
    TEAM ||--o{ RECIPE_BOOK_ENTRY : "keeps"
    RECIPE ||--o{ RECIPE_BOOK_ENTRY : "is kept in"
    CUISINE |o--o{ RECIPE : "classifies"
    RECIPE ||--o{ RECIPE_INGREDIENT : "lists"
    INGREDIENT ||--o{ RECIPE_INGREDIENT : "is used in"
    RECIPE }o--o{ KITCHEN_TOOL : "needs"
    RECIPE ||--o{ RECIPE_EMBEDDING : "is embedded as"
    TEAM ||--o{ WEEKLY_MENU : "plans"
    WEEKLY_MENU ||--|{ MEAL_SLOT : "has 14"
    MEAL_SLOT ||--o{ SLOT_DISH : "serves"
    RECIPE ||--o{ SLOT_DISH : "is served as"
    TEAM ||--o{ INVITATION : "issues"
    TEAM ||--o{ CALENDAR_DAY : "has exceptions on"
    USER ||--o{ ASSISTANT_SESSION : "talks in"
    ASSISTANT_SESSION ||--o{ ATTACHMENT : "has photos"

    TEAM {
        string name
        json typical_week "7 days: active, people per meal"
        int max_weekday_minutes
    }
    RECIPE {
        string title
        string visibility "shared or private"
        int servings "quantities refer to it"
        int_array season_months "derived from ingredients"
        int_array climate_months "suits the weather"
        json provenance "who set each field"
    }
    RECIPE_INGREDIENT {
        decimal quantity "null = to taste"
        string unit "g ml pc tt"
        bool optional
    }
    INGREDIENT {
        string name "normalized, unique"
        string_array aliases
        string category
        int_array season_months "empty = all year"
    }
    MEAL_SLOT {
        date date
        string meal "lunch or dinner"
        int people "0 = nobody at home"
        string outcome "implicit feedback"
    }
    RECIPE_EMBEDDING {
        string model "vectors are per model"
        vector vector "no fixed dimension"
    }
```

Recipes and team preferences point to ingredients by id, never by name: renaming or merging an
ingredient never touches a recipe.

### Decisions worth knowing

- **Team, not family** (2026-10-07): the app serves whoever shares meals (a family, a person
  living alone, flatmates, friends, a sports team, an office). The model is `Team` (formerly
  `Family`) and the API speaks of teams (`/api/teams/`, `team` fields). The Django app lives in
  `apps/teams` but keeps its original label `families`, which keys the migration history and
  the table names (`families_team`, `families_member`, ...); the rename migrations kept every
  row. Technical identifiers that users never see (the Keycloak realm and theme `mymenu`, the
  Compose project `mymenu` and its volume) were left as they are.

- **Shared recipes, per-team recipe book** (confirmed by Paolo 2026-10-05). One `Recipe` row can be in many teams' books.
  A recipe has an **owner team** (the one that created it, the only one that can edit it;
  staff can edit everything) and a **visibility**: `shared` (default, decided 2026-10-06) or
  `private` (only the owner team sees it). `Recipe.objects.visible_to(user)` and
  `editable_by(user)` hold these rules. Creating a recipe through the API puts it in the
  creating team's book. Other teams add a shared recipe to their own book; the owner can
  delete a recipe only while no other team keeps it. Removing a private recipe from the
  owner's book deletes it.
- **Shared catalogs** (ingredients, cuisines, kitchen tools): any user may read and add
  entries, only staff may change or delete them (`CatalogPermission`), because an edit would
  silently change other teams' recipes. Ingredient search matches names and aliases.
  Ingredients and kitchen tools can be added from the recipe editor (no admin needed). The
  kitchen tools the app ships with carry a stable `code` and are shown translated
  (`tool.<code>` in the frontend locales); tools added by users have no code and are shown by
  the name they were given. Tool names are unique regardless of case.
- **Seeded ingredient catalog** (`catalog/migrations/0005_seed_common_ingredients.py`): about 160
  common ingredients in Italian (the first deployment's language) with category, unit, Italian
  seasonality and plural aliases. Idempotent and non-destructive: an entry is skipped when an
  ingredient already exists under its name or one of its aliases. Unlike shipped kitchen tools
  they have no code: ingredient names are data, matched by the assistant in the team's
  language. Database tests start from an empty catalog (`tests/conftest.py`); tests about the
  seed are marked `seeded`.
- **Preserved forms are distinct ingredients** with no season ("pomodoro pelato", "passata di
  pomodoro", "pisello surgelato", "tonno in scatola"): folding them into the fresh product would
  make a winter sauce of peeled tomatoes "in season" only in summer. The assistant's prompts say
  so, and `normalize_draft` forces an all-year season on names that denote a preserved product,
  because the model kept proposing the fresh product's season anyway.
- **Management section** (frontend `/manage`, staff only, from the user menu): one page per
  shared catalog, starting with ingredients: search, category filter, sorting by usage, editing
  (name, aliases, category, unit, season), deleting unused ones, and merging duplicates
  (`catalog/services.py`: recipe lines and preferences move to the target, same-unit quantities
  are added up when a recipe had both, the duplicate's name becomes an alias). Changing an
  ingredient's season re-derives the season of the recipes using it (unless the user set it)
  and refreshes their embeddings.
  This is what makes collaborative recommendation possible ("teams like yours loved X"), and
  keeps discovery candidates separate from accepted recipes (`RecipeBookEntry.Status.CANDIDATE`).
- **People per slot.** The team calendar (typical week plus `CalendarDay` exceptions) says who
  eats at home; `MealSlot.people` is its copy in the week's menu, prefilled by
  `WeeklyMenu.create_empty_slots` and kept in step by `apps.teams.calendar.set_day`.
  `people = 0` means nobody eats at home, and that slot adds nothing to the shopping list.
- **Typical week** (decided with Paolo 2026-10-07). `Team.typical_week` is seven days, Monday
  first, each `{active, breakfast, lunch, dinner}`. A day turned off counts as 0 at every meal
  but keeps its numbers, so turning it back on restores them. It replaced the per-meal
  `default_people` (migration `families.0004` converted it: every day active, nobody at
  breakfast).
- **Calendar exceptions** (`CalendarDay`, `apps/teams/calendar.py`). A date that differs from
  the typical week (guests, someone away, a meal out) stores only the meals that differ, plus an
  optional note; a count equal to the typical week is not stored, and a row left with nothing is
  deleted. An exception can open a day that is usually off. `calendar(team, start, days)` is the
  single source of "who eats at home and what is planned" for the calendar screens and for new
  menus (`WeeklyMenu.create_empty_slots`).
- **One write path for a date** (`set_day`, `PUT /api/calendar/<date>/?team=`, owners only):
  people at some meals, the note, the dishes of some planned meals, each optional and the rest
  kept. Setting dishes creates the week's draft menu if there is none. Clearing a meal or a day
  is people 0 plus no dishes; Undo is the client sending back what it had. `DELETE` brings
  people and note back to the typical week and keeps the dishes. `GET /api/calendar/?team=&
  start=&days=` is open to every member.
- **Breakfast is counted, not planned** (decided with Paolo 2026-10-07). `Meal` includes
  breakfast so the calendar (and later the shopping list) knows who is at home, but the menu
  only gets slots for `PLANNED_MEALS` (lunch and dinner).
- **One or more dishes per slot** (confirmed by Paolo 2026-10-05). `SlotDish` allows e.g. a first course plus a side dish; most
  slots will have one.
- **Implicit feedback lives on the slot.** `MealSlot.outcome` (planned / followed / replaced /
  skipped), with `eaten_instead` when replaced. `rating` and `comment` are the optional explicit
  layer.
- **Seasonality: stored as months, edited by season or by month** (decided with Paolo
  2026-10-05). Storage is always an array of months 1-12; an empty array means "all year". Users
  edit in two modes: **by season** (default; meteorological seasons, e.g. summer = June-August)
  or **by month** (advanced). The API field (`SeasonalityField`) reads as
  `{"months": [...], "seasons": [...], "by_season": bool}`, where `by_season` says whether the
  value is a union of whole seasons and so can be shown in season mode. It accepts
  `{"seasons": [...]}` or `{"months": [...]}` on write, or `{"auto": true}` to hand the value back
  to automatic derivation. A recipe has two levels:
  `season_months` (derived bottom-up via `Recipe.derive_season_months`, the intersection of its
  non-optional ingredients' months, or their union when they do not overlap; recomputed on every
  save until the user sets it) and `climate_months` (whether the dish suits the weather).
  `Recipe.suitable_months()` combines them.
- **Proteins are explicit categories.** `IngredientCategory` separates red meat, white meat, cured
  meat, fish, seafood, egg, legume and cheese, so the "no same protein on adjacent days" rule can
  be checked from data.
- **Kitchen tools that heat the kitchen** (`KitchenTool.heats_kitchen`) are what "avoid the oven in
  summer" is computed from.

### Languages

The interface is multilingual: **Italian by default**, English available (decided 2026-10-05).

- Frontend: i18next (`frontend/src/i18n/`), one JSON file per language under `locales/`. The
  language comes from the user's last choice, then the browser, then Italian. Every visible string
  goes through `t()`; enum values from the API (categories, seasons, outcomes) are translated in
  the frontend from their stable codes.
- Backend: `LANGUAGES = it, en`, `LocaleMiddleware`, and choice labels wrapped in `gettext_lazy`.
  The SPA sends `Accept-Language`, so DRF error messages follow the interface language. Admin
  translation files (`backend/locale/`) need GNU gettext (`brew install gettext`) to generate
  with `makemessages -l it` and are not created yet.
- Code, identifiers and stored codes stay in English. Recipe content (titles, instructions) is
  data and stays in whatever language it was written in.

### Provenance: the user has the final say

Models carrying LLM-suggested or derived properties inherit `ProvenanceMixin`
(`apps/core/provenance.py`): a JSON map `field -> "llm" | "derived" | "user"`.

- Automatic code sets values only through `obj.propose(field, value, Source.LLM | Source.DERIVED)`,
  which refuses to overwrite a field whose source is `user`.
- Every write through the REST API is a user decision: `UserDecisionSerializerMixin` marks the
  fields listed in a serializer's `Meta.tracked_fields` as `user`.

Never assign a tracked field directly from LLM output; always go through `propose`.

### Team management (built 2026-10-07)

The team page (`/team`, from the user menu or the team name in the top bar) covers the profile
(name, weekday time limit, kitchen tools), the typical week, the people at the table
(`Member`: name and birth year, no account needed), users and roles (`Membership`), and
invitations.

- **Owners manage, members read** (`OwnerWritesMixin`, `require_owner` in
  `apps/teams/permissions.py`): profile, people, roles and invitations are changed by owners;
  every member sees them and can leave. Invitation tokens are only ever sent to owners: the token
  *is* the invitation. Before this, any member could change the team and read every link.
- **A team always keeps an owner**: the last owner can neither step down nor leave
  (`MembershipViewSet`); someone else must be made owner first.
- **Teams are not deleted from the app**: it would take every member's recipe book and menus
  with it. New teams are still created by staff (`create_team`), access being invitation-only.
- **Invitations**: a single-use link valid 14 days, copied or shared through the phone's share
  sheet (Web Share API), listed with who created it and who accepted it. No email yet (needs SMTP).
- Tastes (`Preference`) have no screen yet: they come with the menu engine that uses them.

### Navigation (decided with Paolo 2026-10-07)

Material 3 adaptive navigation (`components/Navigation.tsx`): a navigation rail on tablets and
desktops, a bottom navigation bar on phones, for the everyday destinations: **Menu** (the weekly menu and calendar, home,
`/`) and **Recipes** (`/recipes`); the shopping list joins them once it has a screen. The team
page, the management section and the language stay in the user menu: they are visited rarely.
The calendar is also the menu screen ("Menu della settimana"): one week at a time
(`?week=<monday>`), moved by arrows; "Today" appears beside the arrow that leads back to the
current week (its slot is reserved, so nothing shifts), and the week's dates open a month
calendar (MUI X `DateCalendar`) to jump to any date. A row per day
with a card per meal (people, dishes; exceptions in terracotta, nobody at home dimmed). The day's
gear (or its date) opens the day settings, the bin clears the day or a single meal at once with
Undo. A meal card opens the meal page (`/calendar/<date>/<meal>`): people, and the dishes picked
from the recipe book until the menu generator proposes them. Members see everything read-only.

### Multi-team access

A user sees only teams they hold a `Membership` in, and gets one only by accepting an
invitation (or by staff creating the team for them). Viewsets over team-owned data use
`TeamScopedMixin` (`apps/teams/permissions.py`), which filters querysets and rejects writes
pointing at somebody else's team. Global catalogs (ingredients, tools, cuisines, recipes) are
readable and writable by any authenticated user for now.

## Adding recipes (decided with Paolo 2026-10-06)

Built so far: MUI theme, recipe book (search, course filter, "in season" badge, ratings),
recipe page (scaling by number of people, rating, add/remove from book), the recipe editor, the
"+" FAB menu and the assistant in all four modes: "tell me", "help me search", "give me a link"
and "photo". A mode is enabled (`AVAILABLE_MODES` in `apps/assistant/models.py`) only once its
tools exist: offering a
mode before its tools exist would let the LLM invent the content of pages or photos.

```mermaid
flowchart TD
    fab["+ button"] --> tell["Tell me the recipe"]
    fab --> link["Give me a link"]
    fab --> photo["Upload or take a photo"]
    fab --> search["Help me search"]
    fab --> manual["Write it yourself"]

    tell -- "chat model, propose_recipe tool" --> draft
    link -- "fetch page, public only" --> page{"schema.org Recipe?"}
    page -- "yes: facts kept verbatim" --> extract["extraction call<br/>JSON schema"]
    page -- "no: visible text around quantities" --> extract
    photo -- "vision model:<br/>literal transcription" --> extract
    extract --> draft
    search --> local["own and shared recipes:<br/>keywords + embeddings"]
    search --> dishes["3 concrete dishes"] --> websearch["one web search per dish"] --> verify["open each page, keep<br/>single complete recipes"]
    verify -- "Import" --> link
    local -- "Open" --> recipe

    draft["draft<br/>normalize_draft"] -- "corrections in chat" --> draft
    draft --> review["review in the editor<br/>ingredients matched to the catalog"]
    manual --> review
    review -- "Save" --> recipe[("recipe + recipe book entry<br/>+ embedding")]
```

**How the assistant works**

- An `AssistantSession` (team, user, mode) stores the exchange in OpenAI chat format, so a
  draft survives a page reload; only its author sees it.
- Each turn (`apps/assistant/agent.py`) sends a mode-specific system prompt plus the history and
  one tool, `propose_recipe`, whose parameters are the draft schema (`draft.py`). The model
  either asks a short question or calls the tool with the **whole** draft; after each correction
  it calls it again, so the latest call is the current draft. Tool calls and their results stay
  paired in the history. The history is trimmed at user turns to fit the 8k context; when it
  is, the current draft is re-sent as a system note.
- Drafts are normalized (`normalize_draft`): units mapped (kg -> g, "q.b." -> to taste),
  unknown categories/courses fall back to safe values. Measured live 2026-10-06 with
  Qwen3.6-35B-A3B: first draft in 7-16 s, a correction in about 4 s.
- Draft ingredients are matched to the catalog (`apps/catalog/matching.py`): exact name or
  alias, otherwise PostgreSQL trigram similarity (`pg_trgm`), preselecting a candidate from
  0.45 similarity ("pomodori" -> "pomodoro") and flagging it for the user to check.
- "Review and save" opens the editor with `?session=<id>`: matched ingredients are filled in,
  unknown ones must be created (category, unit and season prefilled from the draft) or replaced
  before saving. Saving links the recipe to the session and closes it.
- Gunicorn runs threaded workers so a turn waiting on the LLM does not block other requests.

**Link import** (`apps/assistant/web.py`, built 2026-10-06)

- A message containing a URL, in "tell me" or "link" mode, imports the page instead of asking
  the chat model. One page, the one given, fetched once; no crawling.
- **Only public addresses are fetched**: every redirect hop is checked, and every address the
  host resolves to must be global. `keycloak:8080`, `db`, `host.docker.internal`, LAN and
  loopback addresses are refused (verified from inside the backend container). The page is
  capped at 3 MB and must be HTML. A DNS answer changing between check and connection is not
  covered; acceptable for a team app, revisit before exposing the app widely.
- Text for the model: schema.org `Recipe` data when present, else the visible text with block
  elements split into lines (minified pages are one line otherwise) and cut to a ~9k-character
  window around where quantities cluster.
- A separate extraction call (`response_format` with the draft schema, temperature 0) structures
  the text. Ingredient names are always in the user's language, generic and singular, so they
  match the team catalog (an English page still yields "uovo", "parmigiano"); title,
  description and steps stay in the page's language. Cups, ounces and spoons become g/ml with
  the original measure in the note.
- From structured data, title (site name stripped), servings, times and steps are kept
  verbatim rather than as the model rewrote them; GialloZafferano-style photo numbers in steps
  ("padella antiaderente 4 e") are removed when they form a 1, 2, 3, ... sequence.
- The result is recorded in the history as a `propose_recipe` call, so corrections ("for 2
  people") work as in "tell me"; the source URL survives corrections.
- Failures carry a stable code (`unreachable`, `http_error`, `no_content`, `no_recipe`, ...)
  that the UI translates; the code is stripped from what is sent back to the model.
- Measured live: 9-16 s per import on GialloZafferano, Il Cucchiaio, BBC Good Food, Acadèmia and
  a small blog.

**Photo import** (built 2026-10-06)

- The camera button next to the message box works in every mode (in "photo" mode it is the
  main action); on phones it opens the back camera. The browser downscales to 1280 px JPEG before
  upload (`frontend/src/images.ts`): a 3300x4200 photo became 73 KB, about 1,500 tokens for the
  vision model. The backend accepts only JPEG/PNG/WebP, checked by their bytes, up to 10 MB
  (Traefik sets no body limit).
- Photos are stored in the database (`Attachment`), so they are in the backups, are shown beside
  the draft in the review screen, and are visible only to the conversation's author.
- Two steps, as decided: a strictly literal transcription by the vision model (`LLM_VISION_MODEL`,
  default the chat model), then the same structuring as link import. Compared on synthetic
  cookbook pages and handwritten cards (2026-10-06): with the literal prompt Qwen3.6 transcribed
  faithfully (one inflection wrong), gemma-4-E2B misread words, invented one and reordered a
  paragraph. The review screen shows each photo with the text read from it.
- All photos of a conversation are read together, so a recipe spanning pages is sent as several
  photos. Untested on real photos (blur, real handwriting).
- Measured live: 10-25 s per photo.

**Help me search** (`apps/assistant/search.py`, built 2026-10-06)

- Each message in search mode is a search; earlier messages of the conversation are added as
  context, so "with potatoes" refines the previous request. Picking a web result sends its URL:
  the conversation becomes a link import (mode switches to `link`), and later messages correct
  the draft.
- **Local**: keyword matches first (every meaningful word, roughly stemmed, must appear in the
  title or an ingredient: matching any word turned "un dolce al cioccolato" into a leek soup via
  its "paprika dolce"), then embedding similarity from 0.4. Shown as "in your recipe book" or
  "from other teams" (shared recipes only; private ones never leave their team).
- **Web**: the chat model first turns the request into 3 concrete dishes (about 1 s; vague
  requests otherwise find only category and collection pages), then runs one web search per
  dish through Unsloth Studio's built-in search, two at a time. A result is shown only if its
  page exists, is public, and declares exactly one schema.org Recipe with ingredients and method;
  its title is the page's own. Measured: 22-29 s, 4-6 results.
- What was learned on the way (2026-10-06): asked for JSON, the model invented every URL without
  searching; left free, it chained searches for 90-110 s and nearly filled the context; Studio's
  search tool fails intermittently (the model then answers without links: retried once) and can
  hang up to its 300 s default (capped at 15 s per call).
- **Studio's server-side tools are restricted to `web_search`** (`ai/studio.py`, `SAFE_TOOLS`):
  for local models Studio also offers `python`, `terminal` and `edit_file`, which run on the
  host, and search prompts carry user text. Tool calls per message are capped too.


- **UI library**: MUI (Material UI) with the app's own theme (colours as in `frontend/src/index.css`).
  Material 3's guidance is followed where MUI allows (e.g. labelled FAB menu items).
- **Entry point**: a "+" FAB on the recipe book. **Tap/click always opens the menu** (hover may
  open it early on desktop), with labels always visible, so it behaves the same on touch:
  1. "Tell me the recipe" (first, highlighted): the user describes it, the LLM builds
     ingredients and steps, asking questions only when something essential is missing;
  2. "Help me search": guided search, local recipes first, then the web (Studio's built-in
     search);
  3. "Give me a link": import from a recipe page;
  4. "Upload or take a photo": a cookbook page, a handwritten card, a screenshot.
- **One assistant, three entry points**: the menu items open the same conversational panel in a
  given mode; the LLM still recognizes a pasted link or a search request in any mode.
- **Every path ends in the same draft review** (which doubles as manual entry): everything the
  LLM proposed is editable and marked as suggested (provenance) until the user saves.
  Ingredients are matched to the catalog, or proposed as new with suggested category/season/unit.
- **Visibility**: recipes are **shared by default** with other teams (the collaborative
  recommendation needs a common pool); a team can mark a recipe private.

**Link import** (no crawling, no per-site scrapers; it reads only the page the user gave):

1. schema.org `Recipe` JSON-LD in the page, parsed without any LLM. Checked 2026-10-06: present on
   GialloZafferano, La Cucina Italiana, BBC Good Food, Acadèmia; absent on Il Cucchiaio and on a
   small blog.
2. Otherwise, LLM extraction from the page's visible text into the recipe JSON schema
   (`response_format`). Generic "main content" extractors are not enough: trafilatura dropped Il
   Cucchiaio's ingredient box, losing every quantity. What worked: all visible text, cut to a
   window around where quantities ("320 g", "50 ml") cluster, ~9k characters to fit the context.
   Both pages extracted correctly in 3-6 s.
3. Pages that cannot be read this way (rendered by JavaScript, bot-protected, social/video posts)
   fall back to asking the user to paste the text or take a screenshot (photo mode).

**Photo mode**: a vision-capable model reads the image. Checked 2026-10-06 with a synthetic
handwritten card: both `Qwen3.6-35B-A3B` and `gemma-4-E2B` read it in ~5 s, but Qwen, asked to
"transcribe", **embellished the method with steps not on the card**. So photo import is two
steps: a strictly literal transcription prompt ("only what is written, nothing added"), then the
same structuring as link import, and the review screen shows the source image beside the draft.
Real photos (blur, real handwriting, two-column cookbook pages) are untested.

**Context size**: Studio currently loads the chat model with an 8,192-token context (the model
supports 262k). Page text, images and conversations all count against it; raise it in Studio
when loading the model if long pages or conversations get truncated.

**Build order**: 1. MUI, recipe book, draft review / manual entry; 2. FAB and assistant panel;
3. link import; 4. photo import (reuses link import's structuring); 5. "Tell me the recipe";
6. "Help me search" (needs recipe embeddings first).



Application code depends only on the protocols in `ai/base.py` and on `get_chat_provider()` and
`get_embedding_provider()`. The concrete provider is chosen by environment variables
(`LLM_*`, `EMBEDDINGS_*`, see `.env.example`) through the registries in `ai/factory.py`.

| Provider key | Class | Use |
|---|---|---|
| `openai_compatible` (chat) | `OpenAICompatibleChat` | Any OpenAI-compatible server: llama.cpp, vLLM, Ollama, cloud |
| `unsloth_studio` (chat) | `StudioChat` | Same, plus Studio's `enable_thinking`/`enable_tools` flags and model-loaded checks |
| `openai_compatible` (embeddings) | `OpenAICompatibleEmbeddings` | `services/embeddings`, Studio's `/v1/embeddings`, cloud APIs |

To add a provider: implement the protocol, register it in `ai/factory.py`. Nothing else changes.

### Unsloth Studio

Behaviour verified in the sibling project `../spyone` (Studio 2026.9.2) and carried over:

- Base URL `http://127.0.0.1:8888`; bearer API key from Settings → API keys (`LLM_API_KEY`).
- `{"detail": "Not authenticated"}` means a missing or expired key; 503 means no model loaded.
- Studio serves only the currently loaded chat model, unless **Settings → API → "Switch model by
  request"** is on. `StudioChat.ensure_model_available()` checks this upfront and gives a clear
  error instead of Studio's bare 404.
- Default chat model: `unsloth/Qwen3.6-35B-A3B-MTP-GGUF` (MoE, 3B active), the same one spyone
  uses. `unsloth/gemma-4-E2B-it-GGUF` is the light alternative for fast iteration.
- From inside Docker, Studio is reached at `host.docker.internal:8888` (set in `docker-compose.yml`).

Verified live on 2026-10-05 against this project's adapter:

- **Function calling works**: passing OpenAI-style `tools` returns `finish_reason: "tool_calls"`
  with well-formed `tool_calls` (JSON arguments). This is what the agentic menu engine builds on.
- **`enable_tools: true` turns on Studio's own server-side web search**: the model searched,
  and the source URLs it cited resolved (HTTP 200), not hallucinated. This is the "native web
  search" recipe discovery relies on. Search results inflate the prompt (~1.9k tokens for one
  query). Keep it off for menu generation and on only for discovery.
- "Switch model by request" is on in Paolo's Studio, so a non-resident model is loaded on demand.

### Embeddings

- Default: `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (384 dimensions,
  multilingual, light enough for a Raspberry Pi), served by `services/embeddings`. Vectors are
  L2-normalized, so cosine similarity equals the inner product.
- Embedding tables (`RecipeEmbedding`, `TeamEmbedding`) store the **model name** with each
  vector, and the vector column has **no fixed dimension**. Swapping model means recomputing the
  rows for the new model, with no migration. The trade-off is that pgvector cannot build an ANN
  index on an undimensioned column. At recipe-book scale exact search is fast enough; add a
  dimensioned, indexed column if that ever stops being true.
- `content_hash` records which text was embedded, so stale vectors can be found after edits.
- Recipes are embedded (`apps/recipes/embeddings.py`) from a short document: title, course,
  cuisine, ingredient names, description, the start of the method. On every save, after the
  transaction and best effort (a down embedding service never blocks a save); the one-shot
  `embed-recipes` compose service (`manage.py embed_recipes`, idempotent) catches up on every
  `up`. The embedding service is part of the default stack, with a readiness check that passes
  once the model is loaded.

## Future: translated ingredient names (recorded 2026-10-07)

Ingredient names are stored in a single language (Italian, the first deployment's). A team
using the app in English would see Italian names, and its assistant would create English
duplicates ("tomato" next to "pomodoro").

What makes it tractable: recipes, team preferences and embeddings reference an ingredient by
its id (`RecipeIngredient.ingredient`, `Preference.ingredient` are foreign keys), never by name.
The name is a display and matching attribute only, so translations can be added without touching
any recipe. A possible shape:

- per-language names and aliases on the ingredient (e.g. `names: {"it": "pomodoro", "en":
  "tomato"}`, `aliases: {"it": [...], "en": [...]}`), the current `name` becoming the canonical
  key; the UI shows the name in the interface language, falling back to the canonical one;
- matching (`catalog/matching.py`) and search look at the names and aliases of every language,
  so an English recipe matches the existing "pomodoro";
- the assistant keeps writing ingredient names in the user's language, and a new ingredient gets
  its other-language names proposed by the LLM, to be confirmed in the management section like
  any other suggestion (provenance);
- the seeded catalog gains English names in a data migration.

## Not built yet

Menu generation engine (agentic, RAG), recipe discovery, embedding computation jobs,
collaborative recommendation, a UI for creating invitations, streaming replies, weekly menus
and the shopping list UI.
