# Family Menu Planner

## Project Purpose

**Family Menu Planner** is an application for managing the weekly family menu and the resulting shopping list, driven by a local (or swappable) LLM acting in an agentic way. The goal is to suggest personalized weekly menus, build up a family recipe book over time, and automatically generate the shopping list.

The application is designed from the start to be **parametric and multi-family**: the first use will be single-family (Paolo's family, 3 people), with the stated goal of extending it to friends' families once the system has been tested.

## Conceptual Model

### Weekly Menu

- Made up of 7 days, each with two meal slots: **lunch** and **dinner** (breakfast excluded, for now)
- Each slot has its own **number of people present** for that occasion (typical default: 2 at lunch, 3 at dinner, but overridable: guests, skipped meal = 0 people)
- Each slot links to a recipe, with ingredient quantities scaled to the actual number of people

### Recipe

- Structured ingredients with quantities, referring to a base number of people, mathematically scalable
- Preparation time (must be sustainable for the family)
- Family rating / how much they like it
- **Cuisine type / origin** (e.g. Italian, Japanese, Mexican; traditional or ethnic): used to consciously balance the cultural variety of the menu and as a lever for the LLM's proactivity ("this week let's try something different")
- **Two-level seasonality** tags:
  1. Derived bottom-up from the seasonality of the ingredients that make up the recipe
  2. Semantic climate suitability of the dish itself (e.g. a hot soup remains unsuitable in August even if all its ingredients are available year-round; cold dishes are less likely in winter)
- Required cooking tools (linked to the tool inventory)
- **The LLM proposes and computes automatic derivations, but the user always has the final say** on every property, both at the level of the single ingredient and of the recipe as a whole

### Menu Composition Rules

Nutritional and variety guidelines that frame the LLM's choices, based on common sense and food science. Examples:

- do not repeat the same type of protein on the same day or on adjacent days
- balance food categories across the week
- vary the cuisine type

### Ingredient Catalog (normalized)

- Unique normalized name (avoids duplicates like "tomato" / "tomatoes")
- Reference unit of measure
- Ingredient seasonality (the basis from which recipe seasonality is derived)
- General category (vegetable, animal protein, cereal, dairy, etc.): useful both for nutritional variety rules and for organizing the shopping list by supermarket aisle

### Family Profile (parametric)

- Number of people, changeable at any time
- Age range of members (needed for collaborative recommendations between similar families)
- Food tastes and preferences (no health constraints for now)
- Available kitchen tools (induction hob, microwave, air fryer, conventional oven, etc.): used both for recipe feasibility and for seasonal appropriateness (e.g. avoid the oven in summer)
  - *Future evolution*: automatic inventory via smartphone camera, even if approximate

## Core Features

1. **Structured recipe book**: normalized ingredients, two-level seasonality, cuisine type, times, ratings, composition rules
2. **Parametric family profile**: people, ages, tastes, tools
3. **Weekly menu generation engine (agentic and proactive)**: does not limit itself to the existing recipe book; it actively proposes recipes similar to the ones the family likes to break monotony, integrating with new-recipe discovery
4. **Shopping list generation**: automatic aggregated output from the approved menu
5. **New recipe discovery**: native web search by the LLM, specific user requests (e.g. "a recipe with pumpkin"), and LLM proactivity spotting seasonal gaps in the recipe book; user validation before promotion into the family recipe book
6. **Kitchen tool inventory**: manual setup initially
7. **Feedback and learning**:
   - *Implicit*: confirmation that the proposed menu was followed, or an indication of what was actually eaten instead (a near-zero-cost signal)
   - *Explicit*: optional rating on top of the implicit signal
   - Feedback feeds a **RAG** mechanism (structured data and embeddings retrieved as context at every generation), **not** model fine-tuning
8. **Collaborative recommendation between families**: families with similar composition and ages that liked certain recipes inform suggestions, through vector similarity between family profiles

## Interface

- **Web app** (React, SPA), usable from day one on desktop, designed to be responsive for future mobile use
- Possible future wrapping in **Tauri** for an installable desktop version with local storage (same React codebase, no duplication)
- No "all-in-one" packaging (backend + LLM + frontend in a single executable): deployment flexibility is preferred

## Architectural Principles

- The LLM sits at the center of menu generation and recipe discovery logic, proactive rather than merely reactive
- Total parametricity: no family data hardcoded
- Multi-family design from the data model onward, even though the first use is single-family
- **Swappable LLM components** behind stable interfaces (OpenAI-compatible API style), for both the generative model and embeddings: allows moving between local (Mac, future company Nvidia Spark) and cloud services without touching the rest of the stack
- **Deployment flexibility**: designed to run via Docker Compose, movable between a local ARM64 Mac, a home Raspberry Pi, or a cloud VM

## Future Evolutions (out of initial scope)

- Automatic tool/pantry inventory via smartphone camera
- Native mobile app or other UX extensions
- API/MCP integration with a shopping list app already in use (which would also handle offline use at the supermarket)
- Dedicated recipe scraping, only if the LLM's native web search proves insufficient
- Possible targeted fine-tuning (e.g. on the embedding component), to be evaluated during development
- Semantic enrichment of recipes via a general-purpose online LLM before computing the embedding
- Translated ingredient names, so families using different languages share one catalog (see
  "Future: translated ingredient names" in `docs/architecture.md`)

## Development

Requirements: Docker, [uv](https://docs.astral.sh/uv/), Node 24, and Unsloth Studio running on the
host for the generative LLM.

```bash
python3 scripts/init_env.py   # creates .env and its secrets; then set LLM_API_KEY
                              # (Studio: Settings -> API keys). Social login is optional
docker compose up -d db keycloak
cd backend && uv run python manage.py migrate && uv run python manage.py setup_keycloak
uv run python manage.py runserver
cd ../frontend && npm install && npm run dev    # http://localhost:5173
```

Every step above can be re-run safely. Sign in once, then make yourself owner of the first
family (access is invitation-only):
`uv run python manage.py create_family "My family" --owner you@example.com --staff`.

Or the whole stack in containers: `docker compose up -d --build`, then
http://localhost:8080. Architecture: `docs/architecture.md`; authentication and social login
setup: `docs/authentication.md`; data, backups and moving the stack: `docs/operations.md`.

All data lives in the `mymenu_pgdata` volume: `docker compose down` keeps it, `down -v` deletes
it. Back up with `python3 scripts/backup.py create`.
