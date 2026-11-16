from pathlib import Path

from evaluate import check_fixtures, score


def test_known_defect_fixtures():
    assert check_fixtures(Path(__file__).parent / "fixtures") == {"complex": 3, "small": 1}


def test_unmatched_findings_are_not_called_false_positives():
    result = score({"findings": [{"evidence": []}]}, {"defects": []})
    assert result["unmatched_findings_require_review"] == 1
    assert result["false_positive_findings"] is None
