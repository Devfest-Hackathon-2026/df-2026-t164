"""優先度スコアと復習スケジュールの計算（画面や保存方法に依存しない純粋な関数）。

重みはピッチ資料の「検証前の設計値」。AI の判断ではなく、この Python ロジックで再現可能にする。
  40% 理解不足 / 30% 期限の近さ / 20% 復習の必要性 / 10% 教材の重要度
"""

from __future__ import annotations

from datetime import datetime, timedelta

W_WEAKNESS = 0.40
W_DEADLINE = 0.30
W_REVIEW_NEED = 0.20
W_IMPORTANCE = 0.10

# 復習間隔（日）。インデックスが「定着ステップ」
REVIEW_INTERVAL_DAYS = [1, 3, 7, 14]

# 正答率でステップを動かすしきい値
MASTERED_THRESHOLD = 0.8
WEAK_THRESHOLD = 0.5

DEADLINE_WINDOW_DAYS = 14  # 期限がこの日数以内に入ると加点が始まる


def clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def weakness_component(mastery: float | None) -> float:
    """理解不足。未測定は「わからない」ので最大扱い。"""
    if mastery is None:
        return 1.0
    return clamp01(1.0 - mastery)


def deadline_component(due: datetime | None, now: datetime) -> float:
    """期限の近さ。期限なしは 0、期限当日・超過は 1、14日前から直線で増加。"""
    if due is None:
        return 0.0
    days_left = (due - now).total_seconds() / 86400
    if days_left <= 0:
        return 1.0
    return clamp01(1.0 - days_left / DEADLINE_WINDOW_DAYS)


def review_need_component(next_review_at: datetime | None, now: datetime) -> float:
    """復習の必要性。未学習は 1、予定日を過ぎるほど 1 に近づく、予定日前は 0。"""
    if next_review_at is None:
        return 1.0
    overdue_days = (now - next_review_at).total_seconds() / 86400
    if overdue_days < 0:
        return 0.0
    # 予定日ちょうどで 0.5、1週間遅れでほぼ 1
    return clamp01(0.5 + overdue_days / 14)


def importance_component(importance: int) -> float:
    """教材の重要度（1〜5）を 0〜1 に。"""
    return clamp01((importance - 1) / 4)


def priority_score(
    *,
    mastery: float | None,
    due: datetime | None,
    next_review_at: datetime | None,
    importance: int,
    now: datetime,
) -> dict:
    """0〜100 のスコアと、各要素の内訳を返す。"""
    parts = {
        "weakness": weakness_component(mastery),
        "deadline": deadline_component(due, now),
        "review_need": review_need_component(next_review_at, now),
        "importance": importance_component(importance),
    }
    score = 100 * (
        W_WEAKNESS * parts["weakness"]
        + W_DEADLINE * parts["deadline"]
        + W_REVIEW_NEED * parts["review_need"]
        + W_IMPORTANCE * parts["importance"]
    )
    return {"score": round(score, 1), "breakdown": {k: round(v, 3) for k, v in parts.items()}}


def next_step(current_step: int | None, accuracy: float) -> int:
    """正答率に応じて定着ステップを動かす。高ければ間隔を延ばし、低ければ縮める。"""
    last = len(REVIEW_INTERVAL_DAYS) - 1
    step = 0 if current_step is None else current_step
    if accuracy >= MASTERED_THRESHOLD:
        return min(step + 1, last)
    if accuracy < WEAK_THRESHOLD:
        return max(step - 1, 0)
    return step


def schedule_next_review(step: int, now: datetime) -> datetime:
    return now + timedelta(days=REVIEW_INTERVAL_DAYS[step])


def is_due(next_review_at: datetime | None, now: datetime, mastery: float | None = None) -> bool:
    """今日取り組むべきか。次のいずれかなら True。
    - 予定がまだない（事後テスト未受験）
    - 復習予定日が来た
    - 理解度が低い（しきい値未満）。予定日が先でも、当日は取り組み直せるよう残す
    """
    if next_review_at is None or next_review_at <= now:
        return True
    return mastery is not None and mastery < WEAK_THRESHOLD


def grade(answers: list[int], correct: list[int]) -> tuple[list[bool], float]:
    """採点。解答数が足りない分は不正解として扱う。"""
    results = [i < len(answers) and answers[i] == c for i, c in enumerate(correct)]
    accuracy = sum(results) / len(correct) if correct else 0.0
    return results, accuracy
