from datetime import datetime, timedelta, timezone

import scoring

NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def test_weights_sum_to_one():
    total = scoring.W_WEAKNESS + scoring.W_DEADLINE + scoring.W_REVIEW_NEED + scoring.W_IMPORTANCE
    assert abs(total - 1.0) < 1e-9


def test_max_score_is_100_and_min_is_0():
    hi = scoring.priority_score(mastery=0.0, due=NOW, next_review_at=None, importance=5, now=NOW)
    assert hi["score"] == 100.0
    lo = scoring.priority_score(
        mastery=1.0, due=None, next_review_at=NOW + timedelta(days=3), importance=1, now=NOW
    )
    assert lo["score"] == 0.0


def test_lower_mastery_scores_higher():
    kw = dict(due=None, next_review_at=None, importance=3, now=NOW)
    weak = scoring.priority_score(mastery=0.2, **kw)["score"]
    strong = scoring.priority_score(mastery=0.9, **kw)["score"]
    assert weak > strong


def test_deadline_closer_scores_higher():
    near = scoring.deadline_component(NOW + timedelta(days=1), NOW)
    far = scoring.deadline_component(NOW + timedelta(days=12), NOW)
    assert near > far > 0
    assert scoring.deadline_component(NOW + timedelta(days=30), NOW) == 0.0
    assert scoring.deadline_component(None, NOW) == 0.0
    assert scoring.deadline_component(NOW - timedelta(days=1), NOW) == 1.0


def test_unmeasured_is_treated_as_weakest():
    assert scoring.weakness_component(None) == 1.0


def test_review_need_grows_when_overdue():
    assert scoring.review_need_component(NOW + timedelta(days=1), NOW) == 0.0
    due_today = scoring.review_need_component(NOW, NOW)
    late = scoring.review_need_component(NOW - timedelta(days=7), NOW)
    assert due_today < late <= 1.0


def test_next_step_moves_with_accuracy():
    assert scoring.next_step(None, 1.0) == 1  # 初回で満点 → 間隔を延ばす
    assert scoring.next_step(1, 0.9) == 2
    assert scoring.next_step(3, 1.0) == 3  # 上限
    assert scoring.next_step(2, 0.6) == 2  # 中間は据え置き
    assert scoring.next_step(2, 0.2) == 1  # 低い → 間隔を縮める
    assert scoring.next_step(0, 0.0) == 0  # 下限


def test_schedule_uses_interval_days():
    for step, days in enumerate(scoring.REVIEW_INTERVAL_DAYS):
        assert scoring.schedule_next_review(step, NOW) == NOW + timedelta(days=days)


def test_grade():
    results, acc = scoring.grade([0, 1, 2], [0, 1, 0])
    assert results == [True, True, False]
    assert abs(acc - 2 / 3) < 1e-9
    results, acc = scoring.grade([0], [0, 1])  # 未回答は不正解
    assert results == [True, False] and acc == 0.5
    assert scoring.grade([], []) == ([], 0.0)


def test_is_due():
    assert scoring.is_due(None, NOW)  # 事後テスト未受験
    assert scoring.is_due(NOW - timedelta(days=1), NOW)  # 予定日を過ぎた
    assert scoring.is_due(NOW, NOW)  # 予定日ちょうど
    assert not scoring.is_due(NOW + timedelta(days=3), NOW)
