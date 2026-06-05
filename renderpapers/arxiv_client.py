import arxiv
import hashlib
import json
import os
import pathlib
import re
import requests
import time
import math
from typing import List, Optional
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from urllib.parse import urlparse

# Import Paper model from models
from renderpapers.models import Paper

# Semantic Scholar API (for fetching citation counts)
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper"
CACHE_VERSION = 1


class ArxivSearchError(RuntimeError):
    """Raised when arXiv cannot be reached or returns a non-success status."""

    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def _format_arxiv_error(error: Exception) -> str:
    if isinstance(error, arxiv.HTTPError):
        if error.status == 429:
            return (
                "arXiv API returned HTTP 429 Rate exceeded. "
                "Your IP or proxy is being rate-limited by export.arxiv.org; "
                "stop retrying for a while, then try again with at least a 3 second gap between requests."
            )
        if error.status == 503:
            return (
                "arXiv API returned HTTP 503 Service Unavailable. "
                "This is usually temporary service overload, maintenance, or flow control; "
                "wait a bit and retry."
            )
        return f"arXiv API returned HTTP {error.status}: {error}"

    return f"Could not reach arXiv API: {error}"


def _arxiv_error_status(error: Exception) -> Optional[int]:
    return error.status if isinstance(error, arxiv.HTTPError) else None


def _cache_dir() -> pathlib.Path:
    base = os.environ.get("XDG_CACHE_HOME")
    if base:
        return pathlib.Path(base) / "renderpapers"
    return pathlib.Path.home() / ".cache" / "renderpapers"


def _cache_path(kind: str, payload: dict) -> pathlib.Path:
    cache_key = {
        "version": CACHE_VERSION,
        "kind": kind,
        "payload": payload,
    }
    raw = json.dumps(cache_key, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return _cache_dir() / f"{digest}.json"


def _read_papers_cache(
    path: pathlib.Path,
    cache_ttl_hours: Optional[float],
) -> Optional[List[Paper]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if cache_ttl_hours is not None:
            created_at = datetime.fromisoformat(data["created_at"])
            max_age = timedelta(hours=cache_ttl_hours)
            if datetime.now() - created_at > max_age:
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


def _result_to_paper(result: arxiv.Result) -> Paper:
    arxiv_id = result.get_short_id()
    external_ids = {"ArXiv": arxiv_id}
    if result.doi:
        external_ids["DOI"] = result.doi

    return Paper(
        source="arxiv",
        source_id=arxiv_id,
        title=result.title.replace('\n', ' ').strip(),
        authors=[author.name for author in result.authors],
        abstract=result.summary.replace('\n', ' ').strip(),
        url=result.entry_id,
        pdf_url=result.pdf_url,
        published=result.published.isoformat(),
        updated=result.updated.isoformat(),
        year=result.published.year if result.published else None,
        categories=result.categories,
        primary_category=result.primary_category,
        comment=result.comment,
        journal_ref=result.journal_ref,
        doi=result.doi,
        external_ids=external_ids,
    )


def _execute_search(search: arxiv.Search, max_results: int) -> List[Paper]:
    client = arxiv.Client(
        page_size=max_results,
        delay_seconds=3,  # Recommended delay between queries
        num_retries=3     # Automatically retry on connection failures
    )
    return [_result_to_paper(result) for result in client.results(search)]


def _run_with_cache_and_retry(
    search: arxiv.Search,
    max_results: int,
    cache_kind: str,
    cache_payload: dict,
    use_cache: bool,
    cache_ttl_hours: float,
    retry_on_rate_limit: bool,
    rate_limit_retries: int,
    retry_wait_seconds: float,
) -> List[Paper]:
    cache_file = _cache_path(cache_kind, cache_payload)
    rate_limit_retries = max(0, rate_limit_retries)
    retry_wait_seconds = max(0, retry_wait_seconds)

    if use_cache:
        cached = _read_papers_cache(cache_file, cache_ttl_hours)
        if cached is not None:
            print(f"✓ Loaded {len(cached)} papers from cache")
            return cached

    attempt = 0
    while True:
        try:
            papers = _execute_search(search, max_results=max_results)
            if use_cache:
                _write_papers_cache(cache_file, papers)
            return papers
        except (
            arxiv.HTTPError,
            arxiv.UnexpectedEmptyPageError,
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ) as e:
            status = _arxiv_error_status(e)
            if status == 429 and retry_on_rate_limit and attempt < rate_limit_retries:
                wait_seconds = retry_wait_seconds * (2 ** attempt)
                print(f"⏳ arXiv rate limit hit; retrying in {wait_seconds:g}s...")
                time.sleep(wait_seconds)
                attempt += 1
                continue

            if use_cache:
                stale = _read_papers_cache(cache_file, cache_ttl_hours=None)
                if stale is not None:
                    print(f"⚠️ arXiv failed ({_format_arxiv_error(e)}). Using stale cache.")
                    return stale

            raise ArxivSearchError(_format_arxiv_error(e), status=status) from e


def extract_arxiv_id(value: str) -> Optional[str]:
    """Return an arXiv ID from a bare ID or arxiv.org abs/pdf URL."""
    text = value.strip()
    if not text:
        return None

    parsed = urlparse(text)
    if parsed.netloc.endswith("arxiv.org"):
        parts = parsed.path.strip("/").split("/", 1)
        if len(parts) == 2 and parts[0] in {"abs", "pdf"}:
            arxiv_id = parts[1]
            if arxiv_id.endswith(".pdf"):
                arxiv_id = arxiv_id[:-4]
            return arxiv_id or None

    old_style = r"[a-z-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?"
    new_style = r"\d{4}\.\d{4,5}(?:v\d+)?"
    if re.fullmatch(f"(?:{old_style})|(?:{new_style})", text):
        return text

    return None


def fetch_arxiv_ids(
    arxiv_ids: List[str],
    use_cache: bool = True,
    cache_ttl_hours: float = 24,
    retry_on_rate_limit: bool = False,
    rate_limit_retries: int = 1,
    retry_wait_seconds: float = 30,
) -> List[Paper]:
    search = arxiv.Search(id_list=arxiv_ids, max_results=len(arxiv_ids))
    papers = _run_with_cache_and_retry(
        search=search,
        max_results=len(arxiv_ids),
        cache_kind="ids",
        cache_payload={"id_list": arxiv_ids},
        use_cache=use_cache,
        cache_ttl_hours=cache_ttl_hours,
        retry_on_rate_limit=retry_on_rate_limit,
        rate_limit_retries=rate_limit_retries,
        retry_wait_seconds=retry_wait_seconds,
    )
    print(f"✓ Successfully retrieved {len(papers)} papers")
    return papers


def search_arxiv(
    query: str,
    max_results: int = 50,
    sort_by: str = "relevance",
    sort_order: str = "descending",
    category: Optional[str] = None,
    days_limit: Optional[int] = None,
    use_cache: bool = True,
    cache_ttl_hours: float = 24,
    retry_on_rate_limit: bool = False,
    rate_limit_retries: int = 1,
    retry_wait_seconds: float = 30,
) -> List[Paper]:
    """
    Search arXiv using the official 'arxiv' library.
    """
    
    # 1. Build the search query string
    search_query = query
    if category:
        search_query = f"cat:{category} AND ({query})"

    if days_limit:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days_limit)
        # Construct a date filter in arXiv format
        date_filter = f"submittedDate:[{start_date.strftime('%Y%m%d%H%M')} TO {end_date.strftime('%Y%m%d%H%M')}]"
        search_query = f"({search_query}) AND {date_filter}"

    # 2. Map sorting criteria
    sort_criterion = arxiv.SortCriterion.Relevance
    if sort_by == "lastUpdatedDate":
        sort_criterion = arxiv.SortCriterion.LastUpdatedDate
    elif sort_by == "submittedDate":
        sort_criterion = arxiv.SortCriterion.SubmittedDate

    order = arxiv.SortOrder.Descending if sort_order == "descending" else arxiv.SortOrder.Ascending

    if category:
        print(f"   Filtering by category: {category}")
    
    search = arxiv.Search(
        query=search_query,
        max_results=max_results,
        sort_by=sort_criterion,
        sort_order=order
    )

    papers = _run_with_cache_and_retry(
        search=search,
        max_results=max_results,
        cache_kind="search",
        cache_payload={
            "query": search_query,
            "max_results": max_results,
            "sort_by": sort_by,
            "sort_order": sort_order,
        },
        use_cache=use_cache,
        cache_ttl_hours=cache_ttl_hours,
        retry_on_rate_limit=retry_on_rate_limit,
        rate_limit_retries=rate_limit_retries,
        retry_wait_seconds=retry_wait_seconds,
    )
    print(f"✓ Successfully retrieved {len(papers)} papers")
    return papers

def fetch_citations_batch(papers: List[Paper], batch_size: int = 100) -> List[Paper]:
    """
    Fetch citation counts from Semantic Scholar.
    """
    if not papers:
        return papers
    
    print(f"📊 Fetching citation counts from Semantic Scholar...")
    
    for i in range(0, len(papers), batch_size):
        batch = papers[i:i + batch_size]
        for paper in batch:
            try:
                if not paper.arxiv_id:
                    paper.citations = 0
                    continue
                url = f"{SEMANTIC_SCHOLAR_API}/arXiv:{paper.arxiv_id}"
                response = requests.get(
                    url,
                    params={"fields": "citationCount"},
                    timeout=5
                )
                if response.status_code == 200:
                    data = response.json()
                    paper.citations = data.get("citationCount", 0)
                else:
                    paper.citations = 0
                time.sleep(0.1)  # Avoid hitting API rate limits
            except Exception:
                paper.citations = 0
                continue
    
    total_citations = sum(p.citations or 0 for p in papers)
    print(f"✓ Updated citation info (Total: {total_citations})")
    return papers

def rank_papers(
    query: str,
    papers: List[Paper],
    mode: str = "balanced",
    max_results: int = 20,
) -> List[Paper]:
    """
    Re-rank papers based on different modes.
    """
    if not papers:
        return papers
    
    if mode == "recent":
        sorted_papers = sorted(papers, key=lambda p: p.published or str(p.year or ""), reverse=True)
        return sorted_papers[:max_results]
    
    elif mode == "cited":
        sorted_papers = sorted(
            papers,
            key=lambda p: p.citations if p.citations is not None else 0,
            reverse=True
        )
        return sorted_papers[:max_results]
    
    elif mode == "relevant":
        scored = []
        for paper in papers:
            title_sim = SequenceMatcher(None, query.lower(), paper.title.lower()).ratio()
            abstract_sim = SequenceMatcher(None, query.lower(), paper.abstract.lower()).ratio()
            score = 0.7 * title_sim + 0.3 * abstract_sim
            scored.append((score, paper))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:max_results]]
    
    elif mode == "influential":
        scored = []
        current_year = datetime.now().year
        for paper in papers:
            year = paper.year or int((paper.published or "2000")[:4])
            recency = max(0, (year - 2000) / (current_year - 2000))
            citations = paper.citations if paper.citations is not None else 0
            cite_score = math.log1p(citations) / 10
            score = 0.6 * cite_score + 0.4 * recency
            scored.append((score, paper))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:max_results]]
    
    else:  # balanced
        scored = []
        current_year = datetime.now().year
        for paper in papers:
            title_sim = SequenceMatcher(None, query.lower(), paper.title.lower()).ratio()
            abstract_sim = SequenceMatcher(None, query.lower(), paper.abstract.lower()).ratio()
            relevance = 0.7 * title_sim + 0.3 * abstract_sim
            citations = paper.citations if paper.citations is not None else 0
            cite_score = math.log1p(citations) / 10
            year = paper.year or int((paper.published or "2000")[:4])
            recency = max(0, (year - 2000) / (current_year - 2000))
            score = 0.4 * relevance + 0.35 * cite_score + 0.25 * recency
            scored.append((score, paper))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:max_results]]

def semantic_rank_papers(query: str, papers: List[Paper], max_results: int = 20) -> List[Paper]:
    """
    Rank papers using semantic embeddings.
    Requires: sentence-transformers
    """
    try:
        from sentence_transformers import SentenceTransformer, util
        
        print("⏳ Loading semantic model (all-MiniLM-L6-v2)...")
        model = SentenceTransformer("all-MiniLM-L6-v2")
        
        query_emb = model.encode(query, convert_to_tensor=True)
        
        scored = []
        current_year = datetime.now().year
        
        for paper in papers:
            # Encode Title + Abstract
            text = f"{paper.title} {paper.abstract} {paper.tldr or ''}"
            doc_emb = model.encode(text, convert_to_tensor=True)
            similarity = float(util.cos_sim(query_emb, doc_emb).item())
            
            # Incorporate citation counts and recency factors
            citations = paper.citations if paper.citations is not None else 0
            cite_score = math.log1p(citations) / 10
            
            year = paper.year or int((paper.published or "2000")[:4])
            recency = max(0, (year - 2000) / (current_year - 2000))
            
            # Weighted combined score
            score = 0.6 * similarity + 0.25 * cite_score + 0.15 * recency
            scored.append((score, paper))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored[:max_results]]
        
    except ImportError:
        print("⚠️ sentence-transformers library not installed. Falling back to balanced mode.")
        return rank_papers(query, papers, mode="balanced", max_results=max_results)

if __name__ == "__main__":
    # Quick test
    print("🧪arXiv API...\n")
    
    papers = search_arxiv(
        query="Privileged Information Distillation",
        max_results=5,
        days_limit=365
    )
    
    if papers:
        papers = fetch_citations_batch(papers)
        ranked = rank_papers("Privileged Information Distillation", papers, mode="balanced")
        
        print("\n=== Sample Search Result ===")
        p = ranked[0]
        print(f"Title: {p.title}")
        print(f"Authors: {', '.join(p.authors[:3])}")
        print(f"Published: {p.published[:10]}")
        print(f"Citations: {p.citations}")
        print(f"URL: {p.url or p.arxiv_url}")
    else:
        print("❌ No matching papers found.")
