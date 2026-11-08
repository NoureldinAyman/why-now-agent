import pytest

from why_now.evaluation.score import score

# 6 right yeses, 2 wrong yeses, 4 missed and 8 right no's: precision 0.75, recall 0.6.
EXAMPLE = [(True, True)] * 6 + [(True, False)] * 2 + [(False, True)] * 4 + [(False, False)] * 8


def test_f1_worked_example():
    r = score(EXAMPLE, beta=1)
    assert (r.tp, r.fp, r.fn, r.tn) == (6, 2, 4, 8)
    assert r.precision == 0.75
    assert r.recall == 0.6
    # F1 = 2 * P * R / (P + R) = 0.9 / 1.35
    assert r.f == pytest.approx(2 / 3)
    assert r.beta == 1
    assert r.correct == 14
    assert r.n == 20


def test_beta_half_still_gives_the_old_f05_numbers():
    r = score(EXAMPLE, beta=0.5)
    # F0.5 = 1.25 * P * R / (0.25 * P + R) = 0.5625 / 0.7875
    assert r.f == pytest.approx(0.714285714)
    assert r.beta == 0.5


def test_beta_two_counts_recall_more():
    r = score(EXAMPLE, beta=2)
    # F2 = 5 * P * R / (4 * P + R) = 2.25 / 3.6
    assert r.f == pytest.approx(0.625)


def test_saying_no_to_everything_scores_zero():
    r = score([(False, True), (False, False)], beta=1)
    assert (r.precision, r.recall, r.f) == (0, 0, 0)


def test_one_safe_yes_scores_poorly():
    # Right about the one company it said yes to, but missed nine.
    r = score([(True, True)] + [(False, True)] * 9 + [(False, False)] * 10, beta=1)
    assert r.precision == 1
    assert r.recall == 0.1
    # F1 = 2 * 1 * 0.1 / 1.1
    assert r.f == pytest.approx(0.181818181)


def test_no_rows_is_refused():
    with pytest.raises(ValueError):
        score([], beta=1)


@pytest.mark.parametrize("beta", [0, -1])
def test_a_beta_that_is_not_positive_is_refused(beta):
    with pytest.raises(ValueError):
        score(EXAMPLE, beta=beta)
