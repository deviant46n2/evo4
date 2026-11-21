import json
from pathlib import Path
from .store import EvoStore


def evaluate_memory_retrieval(cases_path, top_k=5):
    """Score lexical memory retrieval against a deterministic, isolated fixture."""
    if int(top_k)<1:
        raise ValueError("top_k must be at least 1")
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
        ids={}
        for index,item in enumerate(memories):
            if not isinstance(item,dict) or not isinstance(item.get("key"),str) or not item["key"].strip():
                raise ValueError(f"Memory #{index+1} requires a nonempty key")
            if item["key"] in ids:
                raise ValueError(f"Duplicate memory key: {item['key']}")
            if not isinstance(item.get("content"),str) or not item["content"].strip():
                raise ValueError(f"Memory {item['key']} requires content")
            ids[item["key"]]=store.add_memory(item["content"],item.get("category","general"),
                                               item.get("tags",[]),source="benchmark",confidence=1.0)
        results=[]
        reciprocal_ranks=[]
        hits=0
        recalls=[]
        for index,case in enumerate(queries):
            if not isinstance(case,dict) or not isinstance(case.get("query"),str) or not case["query"].strip():
                raise ValueError(f"Query #{index+1} requires query text")
            expected=case.get("expected")
            if not isinstance(expected,list) or not expected:
                raise ValueError(f"Query #{index+1} requires a nonempty expected key list")
            unknown=[key for key in expected if key not in ids]
            if unknown:
                raise ValueError(f"Query {case.get('id',index+1)} references unknown memory keys: {unknown}")
            rows=store.search_memories(case["query"],limit=int(top_k))
            ranked=[row["id"] for row in rows]
            relevant={ids[key] for key in expected}
            found=[memory_id for memory_id in ranked if memory_id in relevant]
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
            "hit_rate_at_k":hits/total,
            "mean_recall_at_k":sum(recalls)/total,
            "mean_reciprocal_rank":sum(reciprocal_ranks)/total,
            "results":results,
            "note":"Synthetic isolated benchmark. It measures this retrieval implementation against these fixtures, not recall over a user's real memory collection.",
        }
    finally:
        store.close()
