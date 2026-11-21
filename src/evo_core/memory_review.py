"""Conservative, read-only review suggestions for possibly duplicated memories.

This module uses lexical overlap only. It never merges, edits, archives, or supersedes
records; every result is a suggestion for a human to inspect.
"""
import re
from itertools import combinations

_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "can", "could",
    "did", "do", "does", "for", "from", "had", "has", "have", "how", "i",
    "in", "into", "is", "it", "its", "me", "my", "of", "on", "or", "our",
    "please", "should", "that", "the", "their", "them", "there", "this", "to",
    "use", "used", "using", "was", "we", "what", "when", "where", "which",
    "who", "why", "will", "with", "would", "you", "your",
}


def _terms(value):
    return {
        token for token in re.findall(r"[a-z0-9]+(?:[._'%-][a-z0-9]+)*%?", (value or "").casefold())
        if len(token) > 1 and token not in _STOP
    }


def find_duplicate_candidates(memories, limit=20, min_shared_terms=3):
    """Return bounded possible-duplicate pairs using token overlap, never semantic claims."""
    bounded = min(max(int(limit), 1), 100)
    rows = list(memories or [])[:500]
    prepared = []
    for row in rows:
        item = dict(row)
        terms = _terms(item.get("content", ""))
        if terms:
            prepared.append((item, terms))
    suggestions = []
    for (left, left_terms), (right, right_terms) in combinations(prepared, 2):
        shared = left_terms & right_terms
        if len(shared) < min_shared_terms:
            continue
        union = left_terms | right_terms
        jaccard = len(shared) / len(union) if union else 0.0
        containment = len(shared) / min(len(left_terms), len(right_terms))
        if jaccard < 0.38 and containment < 0.78:
            continue
        score = max(jaccard, containment * 0.92)
        suggestions.append({
            "left": {
                "id": left["id"], "content": left.get("content", ""),
                "category": left.get("category", "general"),
                "source": left.get("source", "unknown"),
                "confidence": float(left.get("confidence", 0.0)),
                "updated_at": left.get("updated_at"),
            },
            "right": {
                "id": right["id"], "content": right.get("content", ""),
                "category": right.get("category", "general"),
                "source": right.get("source", "unknown"),
                "confidence": float(right.get("confidence", 0.0)),
                "updated_at": right.get("updated_at"),
            },
            "similarity": round(min(score, 1.0), 4),
            "jaccard": round(jaccard, 4),
            "containment": round(containment, 4),
            "shared_terms": sorted(shared),
            "reason": "Substantial shared wording; inspect whether these records repeat the same information.",
            "method": "lexical-overlap",
        })
    suggestions.sort(
        key=lambda item: (
            item["similarity"], len(item["shared_terms"]),
            item["left"]["updated_at"] or "", item["right"]["updated_at"] or "",
        ),
        reverse=True,
    )
    # Return a disjoint set of pairs so one popular record cannot monopolize the review list.
    selected, used = [], set()
    for item in suggestions:
        pair = (item["left"]["id"], item["right"]["id"])
        if pair[0] in used or pair[1] in used:
            continue
        selected.append(item)
        used.update(pair)
        if len(selected) >= bounded:
            break
    return selected
