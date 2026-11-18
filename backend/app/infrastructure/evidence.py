"""Keep observed source lines outside lossy, model-written history summaries."""

import json


def retain_source_evidence(previous: dict, observations: list[dict], limit: int) -> dict:
    """Merge exact tool observations, with explicit omissions and a compact read index."""
    sources = {}
    index = list(previous.get("source_evidence_index", []))
    omitted = bool(previous.get("source_evidence_omitted", False))
    for excerpt in previous.get("source_evidence", []):
        sources[excerpt["path"]] = {item["line"]: item["text"] for item in excerpt["lines"]}
    for observation in observations:
        if observation.get("name") != "read_repository_file":
            continue
        output = observation.get("output", {})
        path, lines = output.get("path"), output.get("lines")
        if not isinstance(path, str) or not isinstance(lines, list) or output.get("error"):
            continue
        valid = [
            item
            for item in lines
            if isinstance(item, dict)
            and type(item.get("line")) is int
            and item["line"] > 0
            and isinstance(item.get("text"), str)
        ]
        if not valid:
            continue
        # Most recently observed sources survive first when the context allowance is small.
        current = sources.pop(path, {})
        current.update({item["line"]: item["text"] for item in valid})
        sources[path] = current
        reference = {
            "path": path,
            "start_line": min(item["line"] for item in valid),
            "end_line": max(item["line"] for item in valid),
        }
        if reference not in index:
            index.append(reference)
    excerpts = []
    used = 2
    for path, numbered in reversed(list(sources.items())):
        excerpt = {"path": path, "untrusted": True, "lines": []}
        size = len(json.dumps(excerpt, ensure_ascii=False))
        for line, text in sorted(numbered.items()):
            item = {"line": line, "text": text}
            extra = len(json.dumps(item, ensure_ascii=False)) + 2
            if used + size + extra > limit:
                omitted = True
                continue
            excerpt["lines"].append(item)
            size += extra
        if excerpt["lines"]:
            excerpts.insert(0, excerpt)
            used += size + 2
    return {
        "source_evidence": excerpts,
        "source_evidence_index": index[-128:],
        "source_evidence_omitted": omitted or len(index) > 128,
    }
