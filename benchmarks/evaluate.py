"""Conservative source-grounded scoring, not an automatic semantic correctness oracle."""
import json
from pathlib import Path


def check_fixtures(root: Path):
    counts = {}
    for fixture in sorted(root.iterdir()):
        if not fixture.is_dir():
            continue
        truth = json.loads((fixture / "ground_truth.json").read_text())
        for defect in truth["defects"]:
            line = (fixture / defect["path"]).read_text().splitlines()[defect["line"] - 1]
            assert defect["quote"] in line, f"Stale benchmark ground truth: {defect['id']}"
        counts[fixture.name] = len(truth["defects"])
    return counts


def score(report: dict | None, truth: dict):
    findings = (report or {}).get("findings", [])
    matched = set()
    unmatched = 0
    for finding in findings:
        targets = set()
        for evidence in finding.get("evidence", []):
            for defect in truth["defects"]:
                if (evidence["path"] == defect["path"]
                        and evidence["start_line"] <= defect["line"] <= evidence["end_line"]
                        and (defect["quote"] in evidence["quote"] or evidence["quote"] in defect["quote"])):
                    targets.add(defect["id"])
        if not targets:
            unmatched += 1
        matched |= targets
    return {
        "matched_known_defects": len(matched), "known_defects": len(truth["defects"]),
        "missed_known_defects": sorted(d["id"] for d in truth["defects"] if d["id"] not in matched),
        "unmatched_findings_require_review": unmatched,
        "false_positive_findings": None,
        "scoring_note": "Source/line/quote matches are automated proxies. Semantic correctness and false positives require review.",
    }
