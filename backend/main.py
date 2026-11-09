from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import auth
import generator
import sample
import scoring
from schemas import (
    AnswerResult,
    AnswerSubmit,
    ContentEdit,
    MaterialCreate,
    MeOut,
    MaterialOut,
    QuizOut,
    QuizQuestionPublic,
    ReviewItem,
    RoleSet,
    SharedOut,
    SummaryOut,
)
from schemas import Generated
from store import Attempt, FileData, Material, User, make_store

app = FastAPI(title="SchoolRestart API")

# フロントエンド（開発サーバ）から呼べるようにする。本番のオリジンは環境変数で指定する。
_origins = [o for o in os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",") if o]
app.add_middleware(CORSMiddleware, allow_origins=_origins, allow_methods=["*"], allow_headers=["*"])

store = make_store()


def now() -> datetime:
    return datetime.now(timezone.utc)


# 1人あたりの上限（課金の増えすぎ防止）
MAX_MATERIALS = 20
MAX_GENERATIONS_PER_DAY = 30


def current_user(authorization: str | None = Header(default=None)) -> User:
    """ログイン中のユーザー。初めての人はここで登録する。"""
    if auth.backend() == "firebase":
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(401, "ログインが必要です")
        try:
            ident = auth.verify_token(authorization[7:].strip())
        except auth.AuthError:
            raise HTTPException(401, "ログインの有効期限が切れたか、無効です。もう一度ログインしてください")
    else:
        ident = auth.DEV_IDENTITY
    u = store.get_user(ident.uid)
    if u is None:
        u = User(uid=ident.uid, email=ident.email, name=ident.name)
        store.save_user(u)
    elif not u.name and ident.name:
        u.name = ident.name
        store.save_user(u)
    return u


def _material(material_id: str, user: User) -> Material:
    m = store.get(material_id)
    if m is None or m.owner != user.uid:  # 他人の教材は「無い」ものとして扱う
        raise HTTPException(404, "教材が見つかりません")
    return m


def _teacher_material(material_id: str, user: User) -> Material:
    """先生本人の教材だけ。先生以外は 403。"""
    if user.role != "teacher":
        raise HTTPException(403, "先生のみ使える操作です")
    return _material(material_id, user)


def _check_material_quota(user: User) -> None:
    if len(store.all(owner=user.uid)) >= MAX_MATERIALS:
        raise HTTPException(429, f"教材は1人{MAX_MATERIALS}件までです。不要な教材を整理してください")


def _generations_today(user: User) -> int:
    return user.gen_count if user.gen_date == now().date().isoformat() else 0


def _count_generation(user: User) -> None:
    """AI での生成を1回数える。1日の上限を超えていたら止める。"""
    used = _generations_today(user)
    if used >= MAX_GENERATIONS_PER_DAY:
        raise HTTPException(429, f"AIでの生成は1日{MAX_GENERATIONS_PER_DAY}回までです。明日またお試しください")
    user.gen_date, user.gen_count = now().date().isoformat(), used + 1
    store.save_user(user)


def _out(m: Material) -> MaterialOut:
    return MaterialOut(
        id=m.id,
        title=m.title,
        due_date=m.due_date,
        importance=m.importance,
        created_at=m.created_at,
        file_names=[f.name for f in m.files],
        generated=m.generated is not None,
        mastery=m.mastery,
        review_step=m.review_step,
        next_review_at=m.next_review_at,
        published=m.published,
        shared_from=m.shared_from or None,
    )


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "generator": generator.resolve_backend()}


@app.get("/me", response_model=MeOut)
def me(user: User = Depends(current_user)) -> MeOut:
    return MeOut(
        uid=user.uid,
        email=user.email,
        name=user.name,
        role=user.role,  # type: ignore[arg-type]
        materials_used=len(store.all(owner=user.uid)),
        materials_limit=MAX_MATERIALS,
        generations_today=_generations_today(user),
        generations_limit=MAX_GENERATIONS_PER_DAY,
    )


@app.post("/me/role", response_model=MeOut)
def set_role(body: RoleSet, user: User = Depends(current_user)) -> MeOut:
    """先生/生徒を選ぶ。最初の1回だけ（あとから変えられない）。"""
    if user.role is not None:
        raise HTTPException(409, "役割はすでに選択済みです")
    user.role = body.role
    store.save_user(user)
    return me(user)


@app.post("/materials", response_model=MaterialOut, status_code=201)
def create_material(body: MaterialCreate, user: User = Depends(current_user)) -> MaterialOut:
    _check_material_quota(user)
    m = store.add(
        owner=user.uid,
        title=body.title,
        text=body.text,
        due_date=_aware(body.due_date),
        importance=body.importance,
        created_at=now(),
    )
    return _out(m)


ALLOWED_MIME = {"application/pdf", "image/png", "image/jpeg", "image/webp"}
MAX_FILE_BYTES = 10 * 1024 * 1024  # 1ファイル10MB
MAX_FILES = 5


@app.post("/materials/upload", response_model=MaterialOut, status_code=201)
async def upload_material(
    title: str = Form(min_length=1, max_length=200),
    text: str = Form(default="", max_length=50000),
    due_date: datetime | None = Form(default=None),
    importance: int = Form(default=3, ge=1, le=5),
    files: list[UploadFile] = File(default=[]),
    user: User = Depends(current_user),
) -> MaterialOut:
    """PDF・画像（任意で本文も）から教材を登録する。"""
    _check_material_quota(user)
    files = [f for f in files if f.filename]  # 未選択の空パートを除く
    if not files and not text.strip():
        raise HTTPException(422, "本文かファイルのどちらかは必要です")
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"ファイルは最大{MAX_FILES}個までです")
    saved: list[FileData] = []
    for f in files:
        if f.content_type not in ALLOWED_MIME:
            raise HTTPException(415, f"{f.filename}: 対応形式は PDF / PNG / JPEG / WebP です")
        data = await f.read(MAX_FILE_BYTES + 1)
        if len(data) > MAX_FILE_BYTES:
            raise HTTPException(413, f"{f.filename}: 1ファイル{MAX_FILE_BYTES // 1024 // 1024}MBまでです")
        if not data:
            raise HTTPException(422, f"{f.filename}: 空のファイルです")
        saved.append(FileData(name=f.filename or "file", mime=f.content_type or "", data=data))
    m = store.add(
        owner=user.uid,
        title=title,
        text=text,
        due_date=_aware(due_date),
        importance=importance,
        created_at=now(),
        files=saved,
    )
    return _out(m)


@app.post("/materials/sample", response_model=MaterialOut, status_code=201)
def create_sample_material(user: User = Depends(current_user)) -> MaterialOut:
    """デモ用のサンプル教材を登録する（期限は1週間後）。"""
    _check_material_quota(user)
    t = now()
    m = store.add(
        owner=user.uid,
        title=sample.TITLE,
        text=sample.TEXT,
        due_date=t + timedelta(days=7),
        importance=4,
        created_at=t,
        fallback=sample.FALLBACK,
    )
    return _out(m)


@app.get("/materials", response_model=list[MaterialOut])
def list_materials(user: User = Depends(current_user)) -> list[MaterialOut]:
    return [_out(m) for m in store.all(owner=user.uid)]


@app.get("/materials/{material_id}", response_model=MaterialOut)
def get_material(material_id: str, user: User = Depends(current_user)) -> MaterialOut:
    return _out(_material(material_id, user))


@app.post("/materials/{material_id}/generate", response_model=SummaryOut)
def generate_material(material_id: str, regenerate: bool = False, user: User = Depends(current_user)) -> SummaryOut:
    """要点とクイズを生成する。生成済みなら再利用（regenerate=true で作り直し）。"""
    m = _material(material_id, user)
    if m.source_id and regenerate:
        raise HTTPException(409, "先生から届いた教材は作り直せません")
    if m.generated is None or regenerate:
        _count_generation(user)
        g = generator.generate(m.title, m.text, store.load_files(m))
        # Gemini が使えず代用生成になった場合、手書きの内容があればそちらを使う（デモを止めない）
        if g.source.startswith("dummy") and m.fallback is not None:
            g = m.fallback
        m.generated = g
        store.save(m)
    return SummaryOut(material_id=m.id, summary=m.generated.summary, source=m.generated.source)


@app.get("/materials/{material_id}/summary", response_model=SummaryOut)
def get_summary(material_id: str, user: User = Depends(current_user)) -> SummaryOut:
    m = _material(material_id, user)
    if m.generated is None:
        raise HTTPException(409, "まだ生成されていません。先に /generate を呼んでください")
    return SummaryOut(material_id=m.id, summary=m.generated.summary, source=m.generated.source)


@app.get("/materials/{material_id}/quiz", response_model=QuizOut)
def get_quiz(material_id: str, user: User = Depends(current_user)) -> QuizOut:
    m = _material(material_id, user)
    if m.generated is None:
        raise HTTPException(409, "まだ生成されていません。先に /generate を呼んでください")
    return QuizOut(
        material_id=m.id,
        questions=[QuizQuestionPublic(question=q.question, choices=q.choices) for q in m.generated.questions],
    )


@app.delete("/materials/{material_id}", status_code=204)
def delete_material(material_id: str, user: User = Depends(current_user)) -> None:
    """自分の教材を削除する（ファイル本体も消える）。生徒がコピーした分は残る。"""
    m = _material(material_id, user)
    store.delete(m.id)


@app.get("/materials/{material_id}/content", response_model=Generated)
def get_content(material_id: str, user: User = Depends(current_user)) -> Generated:
    """先生用: 正解つきの要点とクイズ全体（編集画面で使う）。"""
    m = _teacher_material(material_id, user)
    if m.generated is None:
        raise HTTPException(409, "まだ生成されていません。先に /generate を呼んでください")
    return m.generated


@app.put("/materials/{material_id}/content", response_model=MaterialOut)
def edit_content(material_id: str, body: ContentEdit, user: User = Depends(current_user)) -> MaterialOut:
    """先生用: 要点とクイズを編集して保存する。"""
    m = _teacher_material(material_id, user)
    if m.generated is None:
        raise HTTPException(409, "まだ生成されていません。先に /generate を呼んでください")
    m.generated = Generated(summary=body.summary, questions=body.questions, source="teacher")
    store.save(m)
    return _out(m)


@app.post("/materials/{material_id}/publish", response_model=MaterialOut)
def publish_material(material_id: str, user: User = Depends(current_user)) -> MaterialOut:
    """先生用: 生徒に公開する。公開後に編集しても、すでにコピーした生徒の分には反映されない。"""
    m = _teacher_material(material_id, user)
    if m.generated is None:
        raise HTTPException(409, "生成してから公開してください")
    m.published = True
    store.save(m)
    return _out(m)


@app.post("/materials/{material_id}/unpublish", response_model=MaterialOut)
def unpublish_material(material_id: str, user: User = Depends(current_user)) -> MaterialOut:
    m = _teacher_material(material_id, user)
    m.published = False
    store.save(m)
    return _out(m)


@app.get("/shared", response_model=list[SharedOut])
def list_shared(user: User = Depends(current_user)) -> list[SharedOut]:
    """先生が公開した教材の一覧。自分の教材は含めない。"""
    mine = {m.source_id: m.id for m in store.all(owner=user.uid) if m.source_id}
    out: list[SharedOut] = []
    for m in store.published():
        if m.owner == user.uid:
            continue
        teacher = store.get_user(m.owner)
        out.append(
            SharedOut(
                id=m.id,
                title=m.title,
                teacher_name=(teacher.name or teacher.email) if teacher else "先生",
                due_date=m.due_date,
                importance=m.importance,
                added=m.id in mine,
                my_material_id=mine.get(m.id),
            )
        )
    return out


@app.post("/shared/{material_id}/add", response_model=MaterialOut, status_code=201)
def add_shared(material_id: str, user: User = Depends(current_user)) -> MaterialOut:
    """公開された教材を自分用にコピーする（成績は自分だけのものになる）。追加済みならそれを返す。"""
    src = store.get(material_id)
    if src is None or not src.published or src.owner == user.uid or src.generated is None:
        raise HTTPException(404, "教材が見つかりません")
    for m in store.all(owner=user.uid):
        if m.source_id == src.id:
            return _out(m)
    _check_material_quota(user)
    teacher = store.get_user(src.owner)
    m = store.add(
        owner=user.uid,
        title=src.title,
        text="",
        due_date=src.due_date,
        importance=src.importance,
        created_at=now(),
        generated=src.generated.model_copy(deep=True),
        source_id=src.id,
        shared_from=(teacher.name or teacher.email) if teacher else "先生",
    )
    return _out(m)


@app.post("/materials/{material_id}/answers", response_model=AnswerResult)
def submit_answers(material_id: str, body: AnswerSubmit, user: User = Depends(current_user)) -> AnswerResult:
    m = _material(material_id, user)
    if m.generated is None:
        raise HTTPException(409, "まだ生成されていません。先に /generate を呼んでください")
    questions = m.generated.questions
    if len(body.answers) > len(questions):
        raise HTTPException(422, f"解答数が問題数（{len(questions)}）を超えています")
    correct = [q.answer_index for q in questions]
    results, accuracy = scoring.grade(body.answers, correct)

    t = now()
    m.attempts.append(Attempt(kind=body.kind, accuracy=accuracy, at=t))
    if body.kind == "post":  # 事前テストは現状把握のみ。復習予定は事後テストの結果で決める
        m.review_step = scoring.next_step(m.review_step, accuracy)
        m.next_review_at = scoring.schedule_next_review(m.review_step, t)
    store.save(m)
    return AnswerResult(
        kind=body.kind,
        results=results,
        correct_indexes=correct,
        explanations=[q.explanation for q in questions],
        accuracy=round(accuracy, 3),
        mastery=m.mastery if m.mastery is not None else accuracy,
        review_step=m.review_step,
        next_review_at=m.next_review_at,
    )


def _reason(breakdown: dict[str, float], m: Material) -> str:
    if m.mastery is None:
        return "まだ理解度を測っていません"
    labels = {
        "weakness": "理解がまだ不足しています",
        "deadline": "期限が近づいています",
        "review_need": "復習の予定日です",
        "importance": "重要な教材です",
    }
    weights = {
        "weakness": scoring.W_WEAKNESS,
        "deadline": scoring.W_DEADLINE,
        "review_need": scoring.W_REVIEW_NEED,
        "importance": scoring.W_IMPORTANCE,
    }
    top = max(breakdown, key=lambda k: breakdown[k] * weights[k])
    return labels[top]


@app.get("/review", response_model=list[ReviewItem])
def review_list(user: User = Depends(current_user)) -> list[ReviewItem]:
    """優先度スコアの高い順に復習リストを返す。"""
    t = now()
    items: list[ReviewItem] = []
    for m in store.all(owner=user.uid):
        r = scoring.priority_score(
            mastery=m.mastery,
            due=m.due_date,
            next_review_at=m.next_review_at,
            importance=m.importance,
            now=t,
        )
        items.append(
            ReviewItem(
                material_id=m.id,
                title=m.title,
                score=r["score"],
                breakdown=r["breakdown"],
                reason=_reason(r["breakdown"], m),
                due=scoring.is_due(m.next_review_at, t, m.mastery),
                next_review_at=m.next_review_at,
                mastery=m.mastery,
            )
        )
    return sorted(items, key=lambda i: i.score, reverse=True)


# ビルド済みフロントエンド（frontend/dist）があれば同じサービスから配信する（App Engine 用）。
# API のルートを先に登録してあるので、それ以外のパスだけが静的ファイルに回る。
_dist = os.environ.get("FRONTEND_DIST") or os.path.join(os.path.dirname(__file__), "..", "frontend", "dist")
if os.path.isfile(os.path.join(_dist, "index.html")):
    app.mount("/", StaticFiles(directory=_dist, html=True), name="frontend")
