# Job Search Agent — Multi-Source with OpenRouter & OpenAI Agents SDK

> Based on [Job Search Agent by Arindam200](https://github.com/Arindam200/awesome-ai-apps/tree/main/advance_ai_agents/job_finder_agent) — extended with multi-source search, motivation-first matching, and a pluggable open-source scraping stack.

A powerful AI-powered job search agent that finds relevant job opportunities across 35+ job boards based on your resume and career motivation. Built with the OpenAI Agents SDK, Crawl4AI, and pluggable MCP search providers.

## What Changed and Why

The original version was tightly coupled to Bright Data (paid, proprietary) and only searched the Y Combinator job board via a LinkedIn profile URL. This version is a full redesign with the following goals:

- **No paid scraping dependency** — Bright Data replaced with [Crawl4AI](https://crawl4ai.com/) (open-source, local) and a pluggable MCP search layer
- **No LinkedIn URL required** — Users paste their resume or describe their experience directly, which is faster, avoids auth/scraping issues, and works for people who don't have a LinkedIn
- **Cover 35+ job boards** — A single search now fans out to Greenhouse, Lever, Ashby, Indeed, LinkedIn, Wellfound, Workable, Glassdoor, and many more, all selectable by the user
- **Motivation-first matching** — The original matched jobs to current skills. This version prioritizes where the candidate *wants to go*, using a 3-angle keyword strategy (core motivation → adjacent fit → profile baseline)
- **OpenAI Agents SDK** — Replaced the Agno framework with `openai-agents` for explicit agent orchestration and structured JSON handoffs between agents
- **OpenRouter** — Model provider switched to OpenRouter so any model (GPT, Claude, Gemini, etc.) can be used without changing the code — just set `OPENROUTER_API_KEY`
- **Parallel search with concurrency control** — All sources are queried concurrently via `asyncio.gather` with semaphores, making multi-source search practical
- **Pluggable search backend** — `SEARCH_PROVIDER=websearch` (self-hosted Docker, free) or `SEARCH_PROVIDER=firecrawl` (managed API, higher quality)
- **Prompts extracted to `prompts.py`** — All agent instructions are in one file, making it easy to tune behavior without touching orchestration logic
- **Anti-hallucination rules in every prompt** — Agents are explicitly instructed not to invent salary, skills, or tech stack not present in the source data
- **Real-time progress via `@st.fragment`** — Progress updates stream into the UI every 0.5s without a full page rerun (no tab flicker)
- **Download results as Markdown** — One-click export of the full report

## Features

- **Profile input** — Paste resume text or describe experience; add optional motivation/career goals
- **35+ job board sources** — YC Startup Jobs, Indeed, Greenhouse, Lever, Ashby, LinkedIn, Wellfound, Glassdoor, Workday, SmartRecruiters, and more
- **Advanced filters** — Remote only, location, experience level (Junior → Lead/Staff), posting period, expected salary, number of results
- **6-agent pipeline** — Domain classifier → parallel job search → relevance filter → URL normalizer → report generator
- **3-angle keyword strategy** — Each search uses core motivation, adjacent role, and profile baseline keywords for maximum coverage
- **Motivation-first filtering and scoring** — Jobs ranked by how well they match career goals, not just current skills
- **Dual match scores** — Every job gets a Motivation match % and a Skills match % in the final report

## Architecture

```
User Profile + Filters
        │
        ▼
 [Job Suggestions Agent]          ← classifies domain, generates 3 keyword sets
        │
        ▼
 [Build Search Tasks]             ← maps sources to URLs / search queries
        │
   ┌────┴────────────────────────┐
   │ Crawl4AI scrape (YC, Indeed)│   ← async, semaphore(1)
   │ Web Search MCP (all others) │   ← async, semaphore(3)
   └────┬────────────────────────┘
        │ asyncio.gather (parallel)
        ▼
 [Job Search Agent]               ← extracts structured JSON from page content
 [Web Job Searcher Agent]         ← extracts structured JSON from search results
        │
        ▼
 [Job Filter Agent]               ← removes irrelevant / duplicate listings
        │
        ▼
 [URL Parser Agent]               ← normalizes apply links (fixes YC auth URLs etc.)
        │
        ▼
 [Summary Agent]                  ← generates markdown report with match scores
```

## Project Structure

```
job_finder_agent/
├── app.py              # Streamlit UI with @st.fragment live progress
├── job_agents.py       # Agent definitions, URL builders, orchestration
├── mcp_server.py       # Pluggable MCP search backend (websearch / Firecrawl)
├── prompts.py          # All agent instructions in one place
├── pyproject.toml      # Dependencies
├── docker-compose.yml  # websearch-mcp local Docker service
├── assets/             # Static assets
└── .env                # Environment variables (create this)
```

## Prerequisites

- Python 3.10 or higher
- Node.js (for `npx websearch-mcp` or `npx firecrawl-mcp`)
- [OpenRouter](https://openrouter.ai/) account and API key
- Docker (only if using `SEARCH_PROVIDER=websearch`, the default)

## Installation

1. Clone the repository:

```bash
git clone https://github.com/Arindam200/awesome-ai-apps.git
cd advance_ai_agents/job_finder_agent
```

2. Create a virtual environment and install dependencies:

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Using pip
pip install -e .

# Or using uv (recommended)
uv pip install -e .
```

3. Install Crawl4AI browser dependencies (first run only):

```bash
crawl4ai-setup
```

## Configuration

Create a `.env` file in the project root:

```env
# Required
OPENROUTER_API_KEY="your-openrouter-api-key"

# Search provider: "websearch" (default, free, needs Docker) or "firecrawl"
SEARCH_PROVIDER=websearch

# If using websearch: URL of the local Docker service (default shown)
WEBSEARCH_API_URL=http://localhost:3001

# If using firecrawl instead
# SEARCH_PROVIDER=firecrawl
# FIRECRAWL_API_KEY="your-firecrawl-api-key"
```

### Search provider setup

**Option A — websearch (free, self-hosted):**

```bash
docker compose up -d   # starts the websearch-mcp service on port 3001
```

**Option B — Firecrawl (managed, higher quality):**

Get an API key at [firecrawl.dev](https://firecrawl.dev), set `SEARCH_PROVIDER=firecrawl` and `FIRECRAWL_API_KEY` in `.env`. No Docker needed.

## Usage

```bash
streamlit run app.py
```

Open http://localhost:8501, then:

1. In the sidebar, paste your resume or describe your experience
2. Optionally add a motivation note (what role you're looking for)
3. Select job board sources and apply filters
4. Click **Find Jobs** — live progress appears while agents run in the background
5. Review the ranked report and download it as Markdown

## How It Works

1. **Domain & keyword extraction** — The Job Suggestions agent reads your profile and motivation, classifies your domain (Software Engineering, Design, PM, etc.), and generates 3 search keyword sets: core motivation, adjacent role, and profile baseline.

2. **Search task construction** — URLs and queries are built for every selected source using the extracted keywords and active filters (location, remote, experience level, posting period).

3. **Parallel search** — Crawl4AI scrapes YC and Indeed directly; the web search MCP agent handles all other sources. All tasks run concurrently with semaphore-controlled concurrency.

4. **Relevance filtering** — The Job Filter agent removes listings that contradict the candidate's stated motivation, and deduplicates identical postings across sources.

5. **URL normalization** — The URL Parser agent fixes redirect/auth URLs (e.g., YC `signup_job_id` links) to produce direct apply links.

6. **Report generation** — The Summary agent scores each job on Motivation match and Skills match, groups results by source, and produces a structured Markdown report.

## Technical Details

- **Framework**: OpenAI Agents SDK (`openai-agents`)
- **Model provider**: OpenRouter (default model: `openai/gpt-4o-mini`, configurable in `job_agents.py`)
- **Web scraping**: Crawl4AI (async, local, no API key required)
- **Search MCP**: `websearch-mcp` (Docker) or `firecrawl-mcp` (API)
- **UI**: Streamlit with `@st.fragment` for non-blocking live progress
- **Concurrency**: `asyncio.gather` + semaphores (crawl: 1, search: 3)
- **Prompt engineering**: All instructions in `prompts.py` with explicit anti-hallucination constraints

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## Acknowledgments

- [OpenRouter](https://openrouter.ai/) for unified model API access
- [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) for agent orchestration
- [Crawl4AI](https://crawl4ai.com/) for open-source async web scraping
- [Firecrawl](https://firecrawl.dev/) for managed search and scraping
- [Streamlit](https://streamlit.io/) for the web interface framework
