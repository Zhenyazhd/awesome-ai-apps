import os
import json
import logging
import asyncio
from urllib.parse import urlencode
from agents import (
    Agent,
    OpenAIChatCompletionsModel,
    Runner,
    set_tracing_disabled,
)
from openai import AsyncOpenAI
from crawl4ai import AsyncWebCrawler
from mcp_server import make_search_mcp_server
from prompts import (
    JOB_SUGGESTIONS_INSTRUCTIONS,
    JOB_FILTER_INSTRUCTIONS,
    SUMMARY_INSTRUCTIONS,
    URL_PARSER_INSTRUCTIONS,
    job_search_instructions,
    web_search_instructions,
)

logger = logging.getLogger(__name__)

PERIOD_TO_DAYS = {
    "Any": None,
    "Last 24h": 1,
    "Last week": 7,
    "Last month": 30,
}

YC_DOMAIN_MAP = {
    "Software Engineering": "software-engineer",
    "Design & UI/UX": "designer",
    "Product Management": "product-manager",
    "Recruiting & HR": "recruiting-hr",
    "Sales": "sales-manager",
    "Science": "science",
    "Marketing": "marketing",
}

INDEED_QUERY_MAP = {
    "Software Engineering": "software engineer",
    "Design & UI/UX": "ui ux designer",
    "Product Management": "product manager",
    "Recruiting & HR": "recruiter hr",
    "Sales": "sales manager",
    "Science": "data scientist researcher",
    "Marketing": "marketing manager",
}

# Search-based job board sources: (site, inurl)
SEARCH_SOURCES: dict[str, tuple[str, str]] = {
    "Greenhouse":            ("boards.greenhouse.io", ""),
    "Lever":                 ("jobs.lever.co", ""),
    "Ashby":                 ("jobs.ashbyhq.com", ""),
    "Remote Rocketship":     ("remoterocketship.com", ""),
    "LinkedIn":              ("linkedin.com/jobs", ""),
    "Welcome to the Jungle": ("welcometothejungle.com", ""),
    "Pinpoint":              ("pinpointhq.com", ""),
    "Jobs Subdomain":        ("", "jobs"),
    "Careers Pages":         ("", "careers"),
    "People Subdomain":      ("", "people"),
    "Talent Subdomain":      ("", "talent"),
    "Wellfound":             ("wellfound.com", ""),
    "Workable":              ("apply.workable.com", ""),
    "BreezyHR":              ("app.breezy.hr", ""),
    "Workday Jobs":          ("myworkdayjobs.com", ""),
    "Recruitee":             ("recruitee.com", ""),
    "Teamtailor":            ("teamtailor.com", ""),
    "SmartRecruiters":       ("jobs.smartrecruiters.com", ""),
    "JazzHR":                ("app.jazz.co", ""),
    "Jobvite":               ("jobs.jobvite.com", ""),
    "iCIMS":                 ("careers.icims.com", ""),
    "Dover":                 ("dover.com", ""),
    "Builtin":               ("builtin.com", ""),
    "Glassdoor":             ("glassdoor.com", ""),
    "Paylocity":             ("recruiting.paylocity.com", ""),
    "Keka":                  ("keka.com", ""),
    "Oracle Cloud":          ("careers.oracle.com", ""),
    "Rippling":              ("rippling.com/jobs", ""),
    "CareerPuck":            ("careerpuck.com", ""),
    "TalentReef":            ("talentreef.com", ""),
    "Homerun":               ("homerun.team", ""),
    "Trakstar":              ("hire.trakstar.com", ""),
    "ADP":                   ("jobs.adp.com", ""),
    "Factorial":             ("factorialhr.com", ""),
    "TriNet Hire":           ("hire.trinet.com", ""),
    "HelloWork":             ("hellowork.com", ""),
    "Eureka Education":      ("eureka-education.fr", ""),
    "GGE Edu":               ("ggeedu.com", ""),
}

SEARCH_TIMEOUT = 60  # seconds per individual search task


# ---------------------------------------------------------------------------
# URL builders
# ---------------------------------------------------------------------------

def build_yc_url(domain: str, filters: dict) -> str:
    slug = YC_DOMAIN_MAP.get(domain, "")
    base = f"https://ycombinator.com/jobs/role/{slug}" if slug else "https://ycombinator.com/jobs"
    if filters.get("remote"):
        base += "?remote=true"
    return base


def build_indeed_url(domain: str, filters: dict, keywords: str = "") -> str:
    base_query = INDEED_QUERY_MAP.get(domain, domain.lower())
    query = keywords if keywords else base_query
    params = {"q": query, "sort": "date"}
    if filters.get("location"):
        params["l"] = filters["location"]
    elif filters.get("remote"):
        params["l"] = "remote"
    days = PERIOD_TO_DAYS.get(filters.get("period", "Any"))
    if days:
        params["fromage"] = days
    return "https://www.indeed.com/jobs?" + urlencode(params)


def build_search_query(domain: str, filters: dict, site: str, keywords: str = "", inurl: str = "") -> str:
    role = keywords if keywords else INDEED_QUERY_MAP.get(domain, domain.lower())
    parts = [role]
    if inurl:
        parts.append(f"inurl:{inurl}")
    else:
        parts.append(f"site:{site}")
    if filters.get("location"):
        parts.append(filters["location"])
    if filters.get("remote"):
        parts.append("remote")
    if filters.get("experience_level") and filters["experience_level"] != "Any":
        parts.append(filters["experience_level"])
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

def build_agents(
    model: OpenAIChatCompletionsModel,
    mcp_server,
    num_results: int,
    location: str,
    experience_level: str,
    search_provider: str,
) -> dict[str, Agent]:
    return {
        "suggestions": Agent(
            name="Job Suggestions",
            instructions=JOB_SUGGESTIONS_INSTRUCTIONS,
            model=model,
        ),
        "job_search": Agent(
            name="Job Finder",
            instructions=job_search_instructions(num_results, location, experience_level),
            model=model,
        ),
        "web_search": Agent(
            name="Web Job Searcher",
            instructions=web_search_instructions(num_results, search_provider),
            mcp_servers=[mcp_server],
            model=model,
        ),
        "url_parser": Agent(
            name="URL Parser",
            instructions=URL_PARSER_INSTRUCTIONS,
            model=model,
        ),
        "filter": Agent(
            name="Job Filter",
            instructions=JOB_FILTER_INSTRUCTIONS,
            model=model,
        ),
        "summary": Agent(
            name="Summary Agent",
            instructions=SUMMARY_INSTRUCTIONS,
            model=model,
        ),
    }


# ---------------------------------------------------------------------------
# Search task builder
# ---------------------------------------------------------------------------

def build_search_tasks(
    domain: str,
    keywords_list: list[str],
    sources: list[str],
    filters: dict,
) -> tuple[dict[str, str], dict[str, str]]:
    """Return (scrape_tasks, search_query_tasks).

    scrape_tasks:       {source_name: url}         — for Crawl4AI scraping
    search_query_tasks: {task_key: query_string}   — for web search API
    """
    scrape_tasks: dict[str, str] = {}
    if "YC Startup Jobs" in sources:
        scrape_tasks["YC Startup Jobs"] = build_yc_url(domain, filters)
    if "Indeed" in sources:
        scrape_tasks["Indeed"] = build_indeed_url(domain, filters, keywords=keywords_list[0])

    kw_labels = ["core", "adjacent", "baseline"]
    search_query_tasks: dict[str, str] = {}
    for source_name, (site, inurl) in SEARCH_SOURCES.items():
        if source_name not in sources:
            continue
        for i, kw in enumerate(keywords_list[:3]):
            label = kw_labels[i] if i < len(kw_labels) else str(i)
            task_key = f"{source_name} [{label}]"
            search_query_tasks[task_key] = build_search_query(
                domain, filters, site, keywords=kw, inurl=inurl
            )

    return scrape_tasks, search_query_tasks


# ---------------------------------------------------------------------------
# Search executor
# ---------------------------------------------------------------------------

async def _scrape_url(url: str) -> str:
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url=url)
    return result.markdown or ""


async def execute_search_tasks(
    scrape_tasks: dict[str, str],
    search_query_tasks: dict[str, str],
    job_search_agent: Agent,
    web_search_agent: Agent,
    log,
) -> list[dict]:
    """Run all scrape and search tasks concurrently. Returns flat list of job dicts."""
    crawl_sem = asyncio.Semaphore(1)   # Crawl4AI handles 1 request at a time reliably
    search_sem = asyncio.Semaphore(3)  # web search API supports more concurrency

    async def _crawl_and_extract(url: str):
        async with crawl_sem:
            log(f"Crawling {url}...")
            markdown = await _scrape_url(url)
            return await asyncio.wait_for(
                Runner.run(starting_agent=job_search_agent, input=markdown),
                timeout=SEARCH_TIMEOUT,
            )

    async def _web_search(q: str):
        async with search_sem:
            return await asyncio.wait_for(
                Runner.run(starting_agent=web_search_agent, input=q),
                timeout=SEARCH_TIMEOUT,
            )

    all_source_names = list(scrape_tasks.keys()) + list(search_query_tasks.keys())
    all_coros = (
        [_crawl_and_extract(url) for url in scrape_tasks.values()]
        + [_web_search(q) for q in search_query_tasks.values()]
    )

    raw_results = await asyncio.gather(*all_coros, return_exceptions=True)

    all_jobs: list[dict] = []
    for source_name, result in zip(all_source_names, raw_results):
        if isinstance(result, Exception):
            reason = "timeout" if isinstance(result, asyncio.TimeoutError) else type(result).__name__
            log(f"{source_name}: skipped ({reason})")
            continue
        try:
            jobs = json.loads(result.final_output)
            if not isinstance(jobs, list):
                jobs = []
        except Exception:
            jobs = []
        for job in jobs:
            job["source"] = source_name
        all_jobs.extend(jobs)
        log(f"{source_name}: found {len(jobs)} listing(s)")

    return all_jobs


# ---------------------------------------------------------------------------
# Summary input builder
# ---------------------------------------------------------------------------

def build_summary_input(user_profile: str, filters: dict, jobs: list[dict]) -> str:
    parts = []
    if filters.get("location"):
        parts.append(f"Location: {filters['location']}")
    if filters.get("remote"):
        parts.append("Remote only: Yes")
    experience_level = filters.get("experience_level", "Any")
    if experience_level and experience_level != "Any":
        parts.append(f"Experience level: {experience_level}")
    if filters.get("salary_range"):
        parts.append(f"Expected salary: {filters['salary_range']}")
    if filters.get("period") and filters["period"] != "Any":
        parts.append(f"Period: {filters['period']}")

    return json.dumps({
        "profile": user_profile,
        "filters": "\n".join(parts) if parts else "None",
        "jobs": jobs,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

async def run_analysis(user_profile: str, filters: dict | None = None, log_callback=None):
    filters = filters or {}

    def log(msg: str):
        logger.info(msg)
        if log_callback:
            log_callback(msg)

    log("Starting analysis...")
    search_provider = os.environ.get("SEARCH_PROVIDER", "websearch").lower()
    log(f"Initializing MCP server ({search_provider})...")

    client = AsyncOpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=os.environ["OPENROUTER_API_KEY"],
    )
    set_tracing_disabled(disabled=True)

    num_results = filters.get("num_results", 5)
    location = filters.get("location", "")
    experience_level = filters.get("experience_level", "Any")
    sources = filters.get("sources", ["YC Startup Jobs", "Indeed"])

    model = OpenAIChatCompletionsModel(model="openai/gpt-4o-mini", openai_client=client)

    async with make_search_mcp_server() as mcp_server:
        log("MCP server ready")
        agents = build_agents(model, mcp_server, num_results, location, experience_level, search_provider)

        try:
            # 1. Classify domain and extract search keywords
            log("Analyzing your profile to identify professional domain...")
            suggestions_result = await Runner.run(
                starting_agent=agents["suggestions"], input=user_profile
            )
            try:
                domain_data = json.loads(suggestions_result.final_output)
                domain = domain_data.get("selected_domain", "Software Engineering")
                keywords_list = domain_data.get("search_keywords_list", [])
                if isinstance(keywords_list, str):
                    keywords_list = [keywords_list]
                if not keywords_list:
                    keywords_list = [INDEED_QUERY_MAP.get(domain, domain.lower())]
                confidence = domain_data.get("confidence_score", "?")
                reason = domain_data.get("selection_reason", "")
                log(f"Domain identified: {domain} (confidence: {confidence}%) — {reason}")
                log(f"Search angles: {', '.join(keywords_list)}")
            except Exception:
                domain = "Software Engineering"
                keywords_list = [INDEED_QUERY_MAP.get(domain, domain.lower())]
                log(f"Domain identified: {domain}")

            # 2. Build search tasks
            scrape_tasks, search_query_tasks = build_search_tasks(domain, keywords_list, sources, filters)
            total_queries = len(scrape_tasks) + len(search_query_tasks)
            log(f"Searching {total_queries} queries across {len(sources)} source(s)...")
            for name, url in scrape_tasks.items():
                log(f"{name} URL: {url}")

            # 3. Execute all searches in parallel
            all_jobs = await execute_search_tasks(
                scrape_tasks, search_query_tasks,
                agents["job_search"], agents["web_search"],
                log,
            )

            if not all_jobs:
                log("No job listings found. Try different keywords or filters.")
                return (
                    "## No Jobs Found\n\nNo job listings matched your search. Try:\n"
                    "- Different keywords in your motivation\n"
                    "- A broader location or enabling Remote\n"
                    "- A different time period"
                )

            # 4. Filter by relevance
            log("Filtering jobs by relevance to your profile...")
            filter_input = json.dumps({
                "keywords": keywords_list,
                "profile": user_profile[:800],
                "jobs": all_jobs,
            }, ensure_ascii=False)
            filtered_result = await Runner.run(starting_agent=agents["filter"], input=filter_input)
            try:
                filtered_jobs = json.loads(filtered_result.final_output)
                if not isinstance(filtered_jobs, list):
                    filtered_jobs = all_jobs
            except Exception:
                filtered_jobs = all_jobs
            log(f"Relevant jobs after filtering: {len(filtered_jobs)}")

            # 5. Fix YC auth URLs
            log("Processing and cleaning up job URLs...")
            parsed_result = await Runner.run(
                starting_agent=agents["url_parser"],
                input=json.dumps(filtered_jobs, ensure_ascii=False),
            )
            try:
                parsed_jobs = json.loads(parsed_result.final_output)
                if not isinstance(parsed_jobs, list):
                    parsed_jobs = filtered_jobs
            except Exception:
                parsed_jobs = filtered_jobs
            log("URLs processed")

            # 6. Generate report
            log("Generating career analysis report...")
            summary_result = await Runner.run(
                starting_agent=agents["summary"],
                input=build_summary_input(user_profile, filters, parsed_jobs),
            )
            log("Done! Report is ready.")
            return summary_result.final_output

        except Exception as e:
            log(f"Error: {str(e)}")
            logger.error(f"Error during analysis: {str(e)}")
            raise e
