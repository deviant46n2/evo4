import json
from pathlib import Path
from .store import EvoStore


def evaluate_memory_retrieval(cases_path, top_k=5, backend='auto'):
    """Score lexical memory retrieval against a deterministic, isolated fixture."""
    if int(top_k)<1:
        raise ValueError("top_k must be at least 1")
    if backend not in {"auto","fts","fallback"}:
        raise ValueError("backend must be auto, fts, or fallback")
    path=Path(cases_path)
    try:
        data=json.loads(path.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot load memory evaluation cases {path}: {exc}") from exc
    if not isinstance(data,dict) or data.get("version")!=1:
        raise ValueError("Memory evaluation file must be an object with version=1")
    memories=data.get("memories")
    queries=data.get("queries")
    if not isinstance(memories,list) or not isinstance(queries,list) or not memories or not queries:
        raise ValueError("Memory evaluation requires nonempty memories and queries arrays")
    store=EvoStore(":memory:")
    try:
        if backend=="fts" and not store.fts_available:
            raise ValueError("SQLite FTS5 is unavailable in this Python build")
        if backend=="fallback":
            store.fts_available=False
        ids={}
        for index,item in enumerate(memories):
            if not isinstance(item,dict) or not isinstance(item.get("key"),str) or not item["key"].strip():
                raise ValueError(f"Memory #{index+1} requires a nonempty key")
            if item["key"] in ids:
                raise ValueError(f"Duplicate memory key: {item['key']}")
            if not isinstance(item.get("content"),str) or not item["content"].strip():
                raise ValueError(f"Memory {item['key']} requires content")
            tags=item.get("tags",[])
            if not isinstance(tags,list) or any(not isinstance(tag,str) for tag in tags):
                raise ValueError(f"Memory {item['key']} tags must be a list of strings")
            category=item.get("category","general")
            if not isinstance(category,str):
                raise ValueError(f"Memory {item['key']} category must be a string")
            ids[item["key"]]=store.add_memory(item["content"],category,
                                               tags,source="benchmark",confidence=1.0)
        results=[]
        reciprocal_ranks=[]
        hits=0
        recalls=[]
        precisions=[]
        empty_results=0
        for index,case in enumerate(queries):
            if not isinstance(case,dict) or not isinstance(case.get("query"),str) or not case["query"].strip():
                raise ValueError(f"Query #{index+1} requires query text")
            expected=case.get("expected")
            if not isinstance(expected,list) or not expected or any(not isinstance(key,str) or not key for key in expected):
                raise ValueError(f"Query #{index+1} requires a nonempty list of memory keys")
            unknown=[key for key in expected if key not in ids]
            if unknown:
                raise ValueError(f"Query {case.get('id',index+1)} references unknown memory keys: {unknown}")
            rows=store.search_memories(case["query"],limit=int(top_k))
            ranked=[row["id"] for row in rows]
            relevant={ids[key] for key in expected}
            found=[memory_id for memory_id in ranked if memory_id in relevant]
            if not ranked:
                empty_results += 1
            precisions.append(len(set(found))/int(top_k))
            rank=next((i+1 for i,memory_id in enumerate(ranked) if memory_id in relevant),None)
            reciprocal_ranks.append(1.0/rank if rank else 0.0)
            recalls.append(len(set(found))/len(relevant))
            if found:
                hits+=1
            key_by_id={value:key for key,value in ids.items()}
            results.append({
                "id":case.get("id",f"query-{index+1}"),
                "query":case["query"],
                "expected":expected,
                "retrieved":[key_by_id[memory_id] for memory_id in ranked],
                "relevant_retrieved":[key_by_id[memory_id] for memory_id in found],
                "first_relevant_rank":rank,
                "recall_at_k":len(set(found))/len(relevant),
            })
        total=len(queries)
        return {
            "benchmark":str(path),
            "memory_count":len(memories),
            "query_count":total,
            "top_k":int(top_k),
            "backend":backend if backend!="auto" else ("fts" if store.fts_available else "fallback"),
            "hit_rate_at_k":hits/total,
            "mean_recall_at_k":sum(recalls)/total,
            "mean_precision_at_k":sum(precisions)/total,
            "zero_result_rate":empty_results/total,
            "mean_reciprocal_rank":sum(reciprocal_ranks)/total,
            "results":results,
            "note":"Synthetic isolated benchmark. It measures this retrieval implementation against these fixtures, not recall over a user's real memory collection.",
        }
    finally:
        store.close()
