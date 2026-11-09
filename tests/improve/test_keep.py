import pytest

from why_now.evaluation.score import ScoreResult
from why_now.improve.keep import decide_keep


def result(correct: int, f: float, beta: float = 1) -> ScoreResult:
    return ScoreResult(
        tp=0, fp=0, fn=0, tn=0, n=100, correct=correct, precision=0, recall=0, f=f, beta=beta
    )


P = result(100, 0.6)


def test_keep_needs_all_conditions(settings):
    assert decide_keep(result(60, 0.60), result(62, 0.65), P, P, True, settings).keep


def test_tie_is_a_discard(settings):
    r = decide_keep(result(60, 0.60), result(60, 0.60), P, P, True, settings)
    assert not r.keep and r.reasons


def test_one_more_company_is_not_enough(settings):
    assert not decide_keep(result(60, 0.60), result(61, 0.63), P, P, True, settings).keep


def test_more_companies_right_with_a_lower_score_is_a_discard(settings):
    assert not decide_keep(result(60, 0.60), result(62, 0.58), P, P, True, settings).keep


def test_worse_practice_pile_is_a_discard(settings):
    after = result(62, 0.65)
    assert not decide_keep(result(60, 0.60), after, P, result(99, 0.6), True, settings).keep
    assert not decide_keep(result(60, 0.60), after, P, result(100, 0.55), True, settings).keep


def test_failed_hostile_tests_are_a_discard(settings):
    assert not decide_keep(result(60, 0.60), result(62, 0.65), P, P, False, settings).keep


def test_hostile_tests_not_run_yet_is_not_a_keep(settings):
    r = decide_keep(result(60, 0.60), result(62, 0.65), P, P, None, settings)
    assert not r.keep and r.reasons == ["hostile tests needed"]


def test_gain_comes_from_the_setting(settings):
    s = settings.model_copy(update={"keep_min_gain": 1})
    assert decide_keep(result(60, 0.60), result(61, 0.63), P, P, True, s).keep


@pytest.mark.parametrize(
    "odd", ["check_before", "check_after", "practice_before", "practice_after"]
)
def test_scores_with_different_betas_are_refused(settings, odd):
    scores = {
        "check_before": result(60, 0.60),
        "check_after": result(62, 0.65),
        "practice_before": P,
        "practice_after": P,
    }
    scores[odd] = scores[odd].model_copy(update={"beta": 0.5})
    with pytest.raises(ValueError, match="beta"):
        decide_keep(**scores, hostile_passed=True, settings=settings)
