"""教材から要点とクイズを作る。

モードは環境変数 GEMINI_BACKEND で切り替える。
  vertex   : Vertex AI 経由の Gemini（クレジット対象）。GOOGLE_CLOUD_PROJECT / GOOGLE_CLOUD_LOCATION が必要。
             認証は ADC（ローカルは gcloud auth application-default login、App Engine は実行用サービスアカウント）
  aistudio : Google AI Studio の API キー（GEMINI_API_KEY）。無料枠。
  dummy    : Gemini を呼ばず、教材文から機械的に作る。キーなしで一連の流れを動かすための代用。
未設定なら、GOOGLE_CLOUD_PROJECT があれば vertex、GEMINI_API_KEY があれば aistudio、なければ dummy。

Gemini の呼び出しが失敗したら dummy にフォールバックする（当日の生成失敗でも画面を完結させるため）。
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata

from pydantic import BaseModel

from schemas import Generated, QuizQuestion
from store import FileData

log = logging.getLogger("generator")

DEFAULT_MODEL = "gemini-3.8-flash"
NUM_QUESTIONS = 3
NUM_POINTS = 3


def resolve_backend() -> str:
    explicit = os.environ.get("GEMINI_BACKEND", "").strip().lower()
    if explicit in {"vertex", "aistudio", "dummy"}:
        return explicit
    if os.environ.get("GOOGLE_CLOUD_PROJECT"):
        return "vertex"
    if os.environ.get("GEMINI_API_KEY"):
        return "aistudio"
    return "dummy"


# ---- dummy ------------------------------------------------------------

def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。．.!?！？])\s*|\n+", text)
    return [p.strip() for p in parts if len(p.strip()) >= 6]


def generate_dummy(title: str, text: str, source: str = "dummy") -> Generated:
    # ファイルのみの教材は dummy では中身を読めないので、タイトルだけを材料にする
    if text.strip():
        sents = _sentences(text) or [text.strip()]
    else:
        sents = [f"{title}の教材が登録されています。"]
    points = sents[:NUM_POINTS]
    questions: list[QuizQuestion] = []
    for i, correct in enumerate(sents[:NUM_QUESTIONS]):
        others = [s for s in sents if s != correct]
        distractors = (others + ["この教材には書かれていない内容", "上のどれも当てはまらない"])[:3]
        choices = [correct, *distractors]
        # 正解位置が毎回同じにならないよう、問題番号で回す
        shift = i % len(choices)
        choices = choices[-shift:] + choices[:-shift] if shift else choices
        questions.append(
            QuizQuestion(
                question=f"「{title}」について、教材の内容と合っているものはどれ？",
                choices=choices,
                answer_index=choices.index(correct),
                explanation=f"教材に「{correct}」と書かれています。",
            )
        )
    return Generated(summary=points, questions=questions, source=source)  # type: ignore[arg-type]


# ---- gemini -----------------------------------------------------------

class _GeminiOut(BaseModel):
    summary: list[str]

    class Question(BaseModel):
        question: str
        choices: list[str]
        answer_index: int
        explanation: str = ""
        evidence: str = ""

    questions: list[Question]


PROMPT = """あなたは学校の授業を欠席した生徒の学び直しを助ける先生です。
次の教材を読み、日本語で次を作ってください。
- summary: 授業の要点を{n_points}個（各1〜2文）
- questions: 理解度を測る4択問題を{n_q}問。choices は4つ、answer_index は正解の番号（0始まり）、explanation は短い解説、evidence は教材本文からの逐語引用（1〜2文）
- 問題は問う対象を1つに特定してください。「〜について正しいものは」のような広い問い、否定形（「〜でないものはどれ」）、相対判断（「最も適切なものはどれ」）は禁止です。
- 選択肢は同じカテゴリ・粒度・似た長さに揃え、数値や条件は教材の記述をそのまま使ってください。
- evidence は要約・言い換えをせず、教材の文をそのまま1〜2文引用してください。
教材に書かれている内容だけを根拠にしてください。

# タイトル
{title}

# 教材
{text}
"""


def _normalize_evidence(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    value = value.translate(str.maketrans({
        "、": ",",
        "，": ",",
        "．": ".",
        "。": ".",
        "！": "!",
        "？": "?",
    }))
    return re.sub(r"\s+", "", value)


def _evidence_sentences(value: str) -> list[str]:
    return [
        _normalize_evidence(sentence)
        for sentence in re.split(r"(?<=[。．.!?！？])\s*|\n+", value)
        if _normalize_evidence(sentence)
    ]


def _evidence_reason(evidence: str, text: str) -> str | None:
    normalized_evidence = _normalize_evidence(evidence)
    if len(normalized_evidence) < 10:
        return "根拠が空、または短すぎます（10字未満）"
    if not text.strip():
        return None

    normalized_text = _normalize_evidence(text)
    if normalized_evidence in normalized_text:
        return None
    sentences = _evidence_sentences(evidence)
    if sentences and sum(sentence in normalized_text for sentence in sentences) / len(sentences) >= 0.8:
        return None
    return "根拠が教材本文に含まれていません（文単位の一致も8割未満）"


def _validate_questions(questions: list[_GeminiOut.Question], text: str) -> None:
    if not text.strip():
        log.info("教材本文がないため、根拠の本文照合をスキップします（劣化モード）")
    invalid: list[str] = []
    for index, question in enumerate(questions, start=1):
        reason = _evidence_reason(question.evidence, text)
        if reason:
            invalid.append(f"問題{index}: {reason}")
    if invalid:
        for item in invalid:
            log.warning("クイズの根拠チェック不合格: %s", item)
        raise ValueError("; ".join(invalid))


def _client(backend: str):
    from google import genai

    if backend == "vertex":
        return genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.environ.get("GOOGLE_CLOUD_LOCATION", "global"),
        )
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


def generate_gemini(title: str, text: str, backend: str, files: list[FileData] | None = None) -> Generated:
    from google.genai import types

    files = files or []
    body = text if text.strip() else "（本文なし。添付ファイルの内容を教材として扱ってください）"
    for attempt in range(2):
        parts: list = [PROMPT.format(n_points=NUM_POINTS, n_q=NUM_QUESTIONS, title=title, text=body)]
        # PDF・画像は Gemini にそのまま渡す（マルチモーダル）
        parts += [types.Part.from_bytes(data=f.data, mime_type=f.mime) for f in files]

        client = _client(backend)  # 変数に保持する（使い捨てにすると GC で接続が閉じられる）
        resp = client.models.generate_content(
            model=os.environ.get("GEMINI_MODEL", DEFAULT_MODEL),
            contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=_GeminiOut,
                temperature=0.4,
            ),
        )
        out = resp.parsed
        if not isinstance(out, _GeminiOut):
            out = _GeminiOut.model_validate_json(resp.text)
        questions = [q for q in out.questions if 2 <= len(q.choices) and 0 <= q.answer_index < len(q.choices)]
        if not questions or not out.summary:
            raise ValueError("Gemini の出力が不完全です")
        try:
            _validate_questions(questions, text)
        except ValueError:
            if attempt == 0:
                log.warning("クイズの根拠チェック不合格のため、1回だけ再生成します")
                continue
            raise
        return Generated(
            summary=out.summary,
            questions=[QuizQuestion.model_validate(q.model_dump(exclude={"evidence"})) for q in questions],
            source=backend,
        )  # type: ignore[arg-type]
    raise AssertionError("根拠チェックの再生成ループが終了しませんでした")


def generate(title: str, text: str, files: list[FileData] | None = None) -> Generated:
    backend = resolve_backend()
    if backend == "dummy":
        return generate_dummy(title, text)
    try:
        return generate_gemini(title, text, backend, files)
    except Exception:  # 認証・クォータ・出力不正など。内容はログにだけ残す
        log.exception("Gemini の生成に失敗したため dummy にフォールバックします")
        return generate_dummy(title, text, source="dummy-fallback")
