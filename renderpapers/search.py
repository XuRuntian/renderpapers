from renderpapers.sources import ArxivSource, SemanticScholarSource
from renderpapers.sources.base import PaperSearchError, PaperSource


SOURCE_ALIASES = {
    "arxiv": "arxiv",
    "semantic": "semantic-scholar",
    "semantic-scholar": "semantic-scholar",
    "s2": "semantic-scholar",
}


def normalize_source_name(source: str) -> str:
    try:
        return SOURCE_ALIASES[source.lower()]
    except KeyError as exc:
        valid = ", ".join(sorted(set(SOURCE_ALIASES.values())))
        raise PaperSearchError(f"Unknown source '{source}'. Expected one of: {valid}") from exc


def get_source(source: str) -> PaperSource:
    normalized = normalize_source_name(source)
    if normalized == "arxiv":
        return ArxivSource()
    if normalized == "semantic-scholar":
        return SemanticScholarSource()
    raise PaperSearchError(f"Unsupported source: {source}")
