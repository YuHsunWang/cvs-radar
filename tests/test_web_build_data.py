from types import SimpleNamespace

from web.build_data import calibrate_recommendation_score, calibrate_recommendation_scores


def report(key: str, score: float | None, *, confidence: str = "中", consensus: str = "褒貶不一") -> SimpleNamespace:
    return SimpleNamespace(
        product_key=key,
        fair_score=score,
        confidence=confidence,
        consensus=consensus,
    )


def test_recommendation_score_calibration_is_monotonic_and_reaches_nineties() -> None:
    reports = [
        report(f"product-{score}", float(score))
        for score in range(20, 81)
    ]

    calibrated = calibrate_recommendation_scores(reports)
    scores = [calibrated[report.product_key] for report in reports]

    assert scores == sorted(scores)
    assert scores[-1] >= 90
    assert all(0 <= score <= 100 for score in scores)


def test_recommendation_score_calibration_gives_ties_the_same_score() -> None:
    reports = [
        report("lower", 50.0),
        report("tie-a", 75.0),
        report("tie-b", 75.0),
    ]

    calibrated = calibrate_recommendation_scores(reports)

    assert calibrated["tie-a"] == calibrated["tie-b"]
    assert calibrated["lower"] < calibrated["tie-a"]


def test_recommendation_score_calibration_handles_no_scores() -> None:
    reports = [report("missing", None)]

    assert calibrate_recommendation_scores(reports) == {}


def test_recommendation_score_uses_stable_fixed_anchors() -> None:
    assert calibrate_recommendation_score(0) == 0
    assert calibrate_recommendation_score(50) == 60
    assert calibrate_recommendation_score(80) == 93
    assert calibrate_recommendation_score(100) == 100

    original = [report("middle", 60), report("high", 80)]
    before = calibrate_recommendation_scores(original)
    after = calibrate_recommendation_scores(original + [report(f"new-{index}", 20) for index in range(100)])

    assert {key: after[key] for key in before} == before


def test_recommendation_score_omits_low_confidence_reports() -> None:
    reports = [
        report("low", 75, confidence="低", consensus="資料不足"),
        report("enough", 75),
    ]

    assert calibrate_recommendation_scores(reports) == {"enough": 88}
