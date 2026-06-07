import hashlib
import json
import os
import pathlib
import time
from datetime import datetime, timedelta
from typing import Optional, List, Any

import requests

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - python-dotenv is a declared dependency
    load_dotenv = None

from renderpapers.models import Paper, get_category_name
from renderpapers.sources.base import PaperSearchError


SEMANTIC_SCHOLAR_SEARCH_API = "https://api.semanticscholar.org/graph/v1/paper/search"
SEMANTIC_SCHOLAR_PAPER_API = "https://api.semanticscholar.org/graph/v1/paper"
CACHE_VERSION = 1
if load_dotenv:
    load_dotenv()

FIELDS = ",".join([
    "paperId",
    "title",
    "abstract",
    "authors.name",
    "year",
    "publicationDate",
    "venue",
    "citationCount",
    "externalIds",
    "openAccessPdf",
    "url",
    "fieldsOfStudy",
    "publicationTypes",
    "tldr",
])


def _cache_dir() -> pathlib.Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return pathlib.Path(base) / "renderpapers"
    return pathlib.Path.home() / ".cache" / "renderpapers"


def _cache_path(kind: str, payload: dict) -> pathlib.Path:
    cache_key = {"version": CACHE_VERSION, "kind": kind, "payload": payload}
    raw = json.dumps(cache_key, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return _cache_dir() / f"{digest}.json"


def _read_papers_cache(path: pathlib.Path, cache_ttl_hours: Optional[float]) -> Optional[List[Paper]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if cache_ttl_hours is not None:
            created_at = datetime.fromisoformat(data["created_at"])
            if datetime.now() - created_at > timedelta(hours=cache_ttl_hours):
                return None
        return [Paper.model_validate(item) for item in data["papers"]]
    except (OSError, KeyError, ValueError, TypeError):
        return None


def _write_papers_cache(path: pathlib.Path, papers: List[Paper]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "created_at": datetime.now().isoformat(),
            "papers": [paper.model_dump(mode="json") for paper in papers],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return


def _headers() -> dict[str, str]:
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY")
    return {"x-api-key": api_key} if api_key else {}


def _extract_tldr(raw: dict[str, Any]) -> Optional[str]:
    tldr = raw.get("tldr")
    if isinstance(tldr, dict):
        return tldr.get("text")
    if isinstance(tldr, str):
        return tldr
    return None


def _extract_pdf(raw: dict[str, Any]) -> Optional[str]:
    pdf = raw.get("openAccessPdf")
    if isinstance(pdf, dict):
        return pdf.get("url")
    return None


def _normalize_external_ids(raw: dict[str, Any]) -> dict[str, str]:
    external = raw.get("externalIds") or {}
    if not isinstance(external, dict):
        return {}
    return {str(key): str(value) for key, value in external.items() if value}


def _paper_from_semantic(raw: dict[str, Any]) -> Paper:
    external_ids = _normalize_external_ids(raw)
    doi = external_ids.get("DOI")
    categories = raw.get("fieldsOfStudy") or []
    if not isinstance(categories, list):
        categories = []

    authors = []
    for author in raw.get("authors") or []:
        if isinstance(author, dict) and author.get("name"):
            authors.append(author["name"])

    return Paper(
        source="semantic-scholar",
        source_id=raw.get("paperId") or external_ids.get("CorpusId") or external_ids.get("DOI") or "",
        title=(raw.get("title") or "Untitled").replace("\n", " ").strip(),
        authors=authors,
        abstract=(raw.get("abstract") or "").replace("\n", " ").strip(),
        url=raw.get("url") or "",
        pdf_url=_extract_pdf(raw),
        published=raw.get("publicationDate"),
        year=raw.get("year"),
        categories=[str(cat) for cat in categories],
        primary_category=str(categories[0]) if categories else None,
        venue=raw.get("venue") or None,
        doi=doi,
        citations=raw.get("citationCount"),
        external_ids=external_ids,
        tldr=_extract_tldr(raw),
    )


def _semantic_query(query: str, category: Optional[str]) -> str:
    if not category:
        return query
    category_name = get_category_name(category)
    if category_name == category:
        return query
    return f"{query} {category_name}"


def _filter_days(papers: List[Paper], days_limit: Optional[int]) -> List[Paper]:
    if not days_limit:
        return papers

    cutoff = datetime.now().date() - timedelta(days=days_limit)
    filtered = []
    for paper in papers:
        if paper.published:
            try:
                if datetime.fromisoformat(paper.published).date() >= cutoff:
                    filtered.append(paper)
                continue
            except ValueError:
                pass
        if paper.year and paper.year >= cutoff.year:
            filtered.append(paper)
    return filtered


class SemanticScholarSource:
    name = "semantic-scholar"

    def search(
        self,
        query: str,
        max_results: int = 50,
        sort_by: str = "relevance",
        sort_order: str = "descending",
        category: Optional[str] = None,
        venues: Optional[List[str]] = None,
        days_limit: Optional[int] = None,
        use_cache: bool = True,
        cache_ttl_hours: float = 24,
        retry_on_rate_limit: bool = False,
        rate_limit_retries: int = 1,
        retry_wait_seconds: float = 30,
    ) -> List[Paper]:
        request_query = _semantic_query(query, category)
        payload = {
            "query": request_query,
            "max_results": max_results,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "category": category,
            "venues": venues,
            "days_limit": days_limit,
        }
        cache_file = _cache_path("semantic-scholar-search", payload)
        if use_cache:
            cached = _read_papers_cache(cache_file, cache_ttl_hours)
            if cached is not None:
                print(f"✓ Loaded {len(cached)} papers from cache")
                return cached

        params = {"query": request_query, "limit": min(max_results, 100), "fields": FIELDS}
        if venues:
            params["venue"] = ",".join(venues)
        if days_limit:
            cutoff = datetime.now().date() - timedelta(days=days_limit)
            params["publicationDateOrYear"] = f"{cutoff.isoformat()}:"
        attempts = max(1, rate_limit_retries + 1 if retry_on_rate_limit else 1)
        last_error: Optional[Exception] = None
        for attempt in range(attempts):
            try:
                response = requests.get(SEMANTIC_SCHOLAR_SEARCH_API, params=params, headers=_headers(), timeout=20)
                if response.status_code == 429 and retry_on_rate_limit and attempt + 1 < attempts:
                    wait_seconds = max(0, retry_wait_seconds) * (2 ** attempt)
                    print(f"⏳ Semantic Scholar rate limit hit; retrying in {wait_seconds:g}s...")
                    time.sleep(wait_seconds)
                    continue
                if response.status_code >= 400:
                    raise PaperSearchError(
                        f"Semantic Scholar API returned HTTP {response.status_code}: {response.text[:200]}"
                    )
                data = response.json()
                papers = [_paper_from_semantic(item) for item in data.get("data", [])]
                papers = _filter_days(papers, days_limit)
                if use_cache:
                    _write_papers_cache(cache_file, papers)
                print(f"✓ Successfully retrieved {len(papers)} papers")
                return papers
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, ValueError, PaperSearchError) as error:
                last_error = error
                break

        if use_cache:
            stale = _read_papers_cache(cache_file, cache_ttl_hours=None)
            if stale is not None:
                print(f"⚠️ Semantic Scholar failed ({last_error}). Using stale cache.")
                return stale
        raise PaperSearchError(f"Could not reach Semantic Scholar API: {last_error}")

    def fetch_one(
        self,
        identifier: str,
        use_cache: bool = True,
        cache_ttl_hours: float = 24,
        retry_on_rate_limit: bool = False,
        rate_limit_retries: int = 1,
        retry_wait_seconds: float = 30,
    ) -> Optional[Paper]:
        cache_file = _cache_path("semantic-scholar-paper", {"identifier": identifier})
        if use_cache:
            cached = _read_papers_cache(cache_file, cache_ttl_hours)
            if cached is not None:
                print(f"✓ Loaded {len(cached)} papers from cache")
                return cached[0] if cached else None

        response = requests.get(
            f"{SEMANTIC_SCHOLAR_PAPER_API}/{identifier}",
            params={"fields": FIELDS},
            headers=_headers(),
            timeout=20,
        )
        if response.status_code >= 400:
            raise PaperSearchError(f"Semantic Scholar API returned HTTP {response.status_code}: {response.text[:200]}")
        paper = _paper_from_semantic(response.json())
        if use_cache:
            _write_papers_cache(cache_file, [paper])
        print("✓ Successfully retrieved 1 paper")
        return paper
