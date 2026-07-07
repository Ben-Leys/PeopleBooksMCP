from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse


@dataclass(frozen=True, slots=True)
class NormalizedUrl:
    url: str
    path: str


def normalize_oracle_url(url: str, *, base_url: str | None = None) -> NormalizedUrl:
    """Normalize a PeopleBooks URL for stable page identity."""
    absolute_url = urljoin(base_url, url) if base_url else url
    parsed = urlparse(absolute_url)
    query_pairs = parse_qs(parsed.query, keep_blank_values=True)
    filtered_query = {
        key: values
        for key, values in query_pairs.items()
        if key.lower() not in {"focusnode", "ctx"}
    }
    normalized_query = urlencode(filtered_query, doseq=True)
    normalized = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        path=parsed.path,
        params="",
        query=normalized_query,
        fragment="",
    )
    return NormalizedUrl(url=urlunparse(normalized), path=normalized.path)


def oracle_source_metadata(url: str) -> dict[str, object]:
    parsed = urlparse(url)
    path_parts = [part for part in parsed.path.split("/") if part]
    query = {
        key: values[0] if len(values) == 1 else values
        for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
    }

    metadata: dict[str, object] = {
        "source": "oracle_peoplebooks",
        "host": parsed.netloc.lower(),
        "query": query,
    }
    if len(path_parts) >= 6 and path_parts[0] == "cd":
        metadata["doc_version_path"] = path_parts[2]
        metadata["language"] = path_parts[3]
        metadata["product"] = path_parts[4]
    return metadata
