from typing import Optional, List

from renderpapers.arxiv_client import fetch_arxiv_ids, search_arxiv
from renderpapers.models import Paper
from renderpapers.sources.base import PaperSearchError


class ArxivSource:
    name = "arxiv"

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
        if venues:
            raise PaperSearchError(
                "Venue filtering is only supported by the Semantic Scholar source."
            )
        return search_arxiv(
            query=query,
            max_results=max_results,
            sort_by=sort_by,
            sort_order=sort_order,
            category=category,
            days_limit=days_limit,
            use_cache=use_cache,
            cache_ttl_hours=cache_ttl_hours,
            retry_on_rate_limit=retry_on_rate_limit,
            rate_limit_retries=rate_limit_retries,
            retry_wait_seconds=retry_wait_seconds,
        )

    def fetch_one(
        self,
        identifier: str,
        use_cache: bool = True,
        cache_ttl_hours: float = 24,
        retry_on_rate_limit: bool = False,
        rate_limit_retries: int = 1,
        retry_wait_seconds: float = 30,
    ) -> Optional[Paper]:
        papers = fetch_arxiv_ids(
            [identifier],
            use_cache=use_cache,
            cache_ttl_hours=cache_ttl_hours,
            retry_on_rate_limit=retry_on_rate_limit,
            rate_limit_retries=rate_limit_retries,
            retry_wait_seconds=retry_wait_seconds,
        )
        return papers[0] if papers else None
