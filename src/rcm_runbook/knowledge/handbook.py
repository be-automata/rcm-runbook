"""Heading-indexed keyword lookup over the RCM knowledge docs.

Deterministic and dependency-free (v1). Upgrade path: swap internals for Agno
Knowledge + vector search without changing `consult(query)`'s signature.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

DOCS_DIR = Path(__file__).parents[3].parent / "docs"

_SOURCES = ("rcm_handbook_com.md", "client_method_20_steps.md")

_MAX_SECTION_CHARS = 2400
_MAX_RESULTS = 3


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def _docs_dir() -> Path:
    here = Path(__file__).resolve()
    # Installed as a wheel: docs are force-included at rcm_runbook/_docs
    packaged = here.parent.parent / "_docs"
    if (packaged / _SOURCES[0]).exists():
        return packaged
    # Repo layout: <root>/docs next to <root>/src
    for parent in here.parents:
        candidate = parent / "docs" / _SOURCES[0]
        if candidate.exists():
            return parent / "docs"
    return Path("docs")


@lru_cache(maxsize=1)
def _sections() -> list[tuple[str, str, str]]:
    """(source, heading, body) triples split on markdown headings."""
    out: list[tuple[str, str, str]] = []
    for name in _SOURCES:
        path = _docs_dir() / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        parts = re.split(r"^(#{1,4} .+)$", text, flags=re.MULTILINE)
        heading = "(inicio)"
        for part in parts:
            if re.match(r"^#{1,4} ", part):
                heading = part.lstrip("# ").strip()
            else:
                body = part.strip()
                if body:
                    out.append((name, heading, body[:_MAX_SECTION_CHARS]))
    return out


def consult(query: str) -> str:
    """Return the most relevant handbook/method sections for `query` (Spanish ok)."""
    terms = [t for t in re.split(r"\W+", _normalize(query)) if len(t) > 2]
    if not terms:
        return "Indique un tema a consultar (p.ej. 'intervalo P-F', 'búsqueda de fallas')."
    scored: list[tuple[float, str, str, str]] = []
    for source, heading, body in _sections():
        haystack = _normalize(heading) + " " + _normalize(body)
        score = sum(haystack.count(t) for t in terms)
        score += sum(3 for t in terms if t in _normalize(heading))
        if score > 0:
            scored.append((score, source, heading, body))
    scored.sort(key=lambda x: -x[0])
    if not scored:
        return (
            f"No se encontró contenido sobre '{query}' en el manual RCM "
            "ni en el método del cliente."
        )
    blocks = [
        f"### {heading}  \n(fuente: {source})\n\n{body}"
        for _, source, heading, body in scored[:_MAX_RESULTS]
    ]
    return "\n\n---\n\n".join(blocks)
