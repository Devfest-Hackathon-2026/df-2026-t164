"""API の入出力の形。フロントエンドとの境界なので、変更するときは双方に相談する。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class MaterialCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50000)
    due_date: datetime | None = None  # テストなどの期限
    importance: int = Field(default=3, ge=1, le=5)


class QuizQuestion(BaseModel):
    question: str
    choices: list[str]
    answer_index: int
    explanation: str = ""


class QuizQuestionPublic(BaseModel):
    """学習者向け。正解は含めない。"""

    question: str
    choices: list[str]


class Generated(BaseModel):
    """生成物の保存形式。同じ教材は再解析しないよう再利用する。"""

    summary: list[str]  # 要点
    questions: list[QuizQuestion]
    source: Literal["vertex", "aistudio", "dummy", "dummy-fallback", "teacher"]


class MaterialOut(BaseModel):
    id: str
    title: str
    due_date: datetime | None
    importance: int
    created_at: datetime
    file_names: list[str] = []  # 添付ファイル名（PDF・画像）
    generated: bool
    mastery: float | None
    review_step: int | None
    next_review_at: datetime | None
    published: bool = False  # 先生が公開中か
    shared_from: str | None = None  # 先生から届いた教材なら、先生の名前


class SummaryOut(BaseModel):
    material_id: str
    summary: list[str]
    source: str


class QuizOut(BaseModel):
    material_id: str
    questions: list[QuizQuestionPublic]


class AnswerSubmit(BaseModel):
    kind: Literal["pre", "post"] = "post"  # 事前テスト / 事後テスト
    answers: list[int]


class AnswerResult(BaseModel):
    kind: str
    results: list[bool]
    correct_indexes: list[int]
    explanations: list[str]
    accuracy: float
    mastery: float
    review_step: int | None  # 事前テストの場合は None（まだ復習予定なし）
    next_review_at: datetime | None


class ReviewItem(BaseModel):
    material_id: str
    title: str
    score: float
    breakdown: dict[str, float]
    reason: str
    due: bool  # 今日取り組むべきか（復習予定日が来た / 事後テスト未受験 / 理解度が低い）
    next_review_at: datetime | None
    mastery: float | None


class ContentEdit(BaseModel):
    """先生が編集した要点とクイズ。"""

    summary: list[str] = Field(min_length=1, max_length=20)
    questions: list[QuizQuestion] = Field(min_length=1, max_length=20)

    @field_validator("summary")
    @classmethod
    def _summary_not_blank(cls, v: list[str]) -> list[str]:
        v = [s.strip() for s in v]
        if any(not s for s in v):
            raise ValueError("要点に空の項目があります")
        return v

    @model_validator(mode="after")
    def _check_questions(self) -> "ContentEdit":
        for i, q in enumerate(self.questions, start=1):
            q.question = q.question.strip()
            q.choices = [c.strip() for c in q.choices]
            if not q.question:
                raise ValueError(f"問題{i}: 問題文が空です")
            if not 2 <= len(q.choices) <= 6:
                raise ValueError(f"問題{i}: 選択肢は2〜6個にしてください")
            if any(not c for c in q.choices):
                raise ValueError(f"問題{i}: 空の選択肢があります")
            if not 0 <= q.answer_index < len(q.choices):
                raise ValueError(f"問題{i}: 正解の番号が選択肢の範囲外です")
        return self


class SharedOut(BaseModel):
    """先生が公開した教材（生徒向けの一覧）。"""

    id: str
    title: str
    teacher_name: str
    due_date: datetime | None
    importance: int
    added: bool  # すでに自分の教材に追加済みか
    my_material_id: str | None  # 追加済みなら、自分用の教材ID


class MeOut(BaseModel):
    uid: str
    email: str
    name: str
    role: Literal["teacher", "student"] | None  # None = まだ選んでいない
    materials_used: int  # 登録済みの教材数
    materials_limit: int
    generations_today: int
    generations_limit: int


class RoleSet(BaseModel):
    role: Literal["teacher", "student"]


class ErrorOut(BaseModel):
    detail: str
