import arxiv
import requests
import time
import math
from typing import List, Optional
from datetime import datetime, timedelta
from difflib import SequenceMatcher

# Import Paper model from models
from renderarxiv.models import Paper

# Semantic Scholar API (for fetching citation counts)
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1/paper"


class ArxivSearchError(RuntimeError):
    """Raised when arXiv cannot be reached or returns a non-success status."""


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


def search_arxiv(
    query: str,
    max_results: int = 50,
    sort_by: str = "relevance",
    sort_order: str = "descending",
    category: Optional[str] = None,
    days_limit: Optional[int] = None,
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
    
    # 3. Initialize client (configured with retry logic for SSL/connection issues)
    client = arxiv.Client(
        page_size=max_results,
        delay_seconds=3,  # Recommended delay between queries
        num_retries=3     # Automatically retry on connection failures
    )

    search = arxiv.Search(
        query=search_query,
        max_results=max_results,
        sort_by=sort_criterion,
        sort_order=order
    )

    try:
        papers = []
        # Execute search and iterate through results
        for result in client.results(search):
            # Convert arxiv.Result object to custom Paper object
            paper = Paper(
                arxiv_id=result.get_short_id(),
                title=result.title.replace('\n', ' ').strip(),
                authors=[author.name for author in result.authors],
                abstract=result.summary.replace('\n', ' ').strip(),
                pdf_url=result.pdf_url,
                arxiv_url=result.entry_id,
                published=result.published.isoformat(),
                updated=result.updated.isoformat(),
                categories=result.categories,
                primary_category=result.primary_category,
                comment=result.comment,
                journal_ref=result.journal_ref,
                doi=result.doi,
            )
            papers.append(paper)

        print(f"✓ Successfully retrieved {len(papers)} papers")
        return papers

    except (
        arxiv.HTTPError,
        arxiv.UnexpectedEmptyPageError,
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
    ) as e:
        raise ArxivSearchError(_format_arxiv_error(e)) from e

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
        sorted_papers = sorted(papers, key=lambda p: p.published, reverse=True)
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
            year = int(paper.published[:4])
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
            year = int(paper.published[:4])
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
            text = f"{paper.title} {paper.abstract}"
            doc_emb = model.encode(text, convert_to_tensor=True)
            similarity = float(util.cos_sim(query_emb, doc_emb).item())
            
            # Incorporate citation counts and recency factors
            citations = paper.citations if paper.citations is not None else 0
            cite_score = math.log1p(citations) / 10
            
            year = int(paper.published[:4])
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
        print(f"URL: {p.arxiv_url}")
    else:
        print("❌ No matching papers found.")
