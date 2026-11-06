import pytest

from why_now.evaluation.score import score


def test_f05_worked_example():
    # 6 right yeses, 2 wrong yeses, 4 missed and 8 right no's.
    r = score([(True, True)] * 6 + [(True, False)] * 2 + [(False, True)] * 4 + [(False, False)] * 8)
    assert (r.tp, r.fp, r.fn, r.tn) == (6, 2, 4, 8)
    assert r.precision == 0.75
    assert r.recall == 0.6
    # F0.5 = 1.25 * P * R / (0.25 * P + R) = 0.5625 / 0.7875
    assert r.f05 == pytest.approx(0.714285714)
    assert r.correct == 14
    assert r.n == 20


def test_saying_no_to_everything_scores_zero():
    r = score([(False, True), (False, False)])
    assert (r.precision, r.recall, r.f05) == (0, 0, 0)


def test_one_safe_yes_scores_poorly():
    # Right about the one company it said yes to, but missed nine.
    r = score([(True, True)] + [(False, True)] * 9 + [(False, False)] * 10)
    assert r.precision == 1
    assert r.recall == 0.1
    assert r.f05 == pytest.approx(0.357142857)


def test_no_rows_is_refused():
    with pytest.raises(ValueError):
        score([])
