"""教材データの保存。アクセスはこのモジュールに閉じ込める。

- MemoryStore: メモリ上（再起動で消える）。ローカル開発・テスト用。既定。
- DatastoreStore: Firestore(Datastore モード) に本文・成績を、Cloud Storage にファイル本体を保存。
  環境変数 STORE_BACKEND=datastore で有効になる。
呼び出し側は、Material を書き換えたら store.save(m) を呼ぶ。
"""

from __future__ import annotations

import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from schemas import Generated


@dataclass
class FileData:
    """アップロードされた教材ファイル（PDF・画像）。いまはメモリ上。のちに Cloud Storage へ。"""

    name: str
    mime: str
    data: bytes = b""
    path: str = ""  # Cloud Storage 上の場所（DatastoreStore のとき）


@dataclass
class Attempt:
    kind: str
    accuracy: float
    at: datetime


@dataclass
class User:
    uid: str
    email: str = ""
    name: str = ""
    role: str | None = None  # "teacher" | "student"。初回に1度だけ選ぶ
    gen_date: str = ""  # 生成回数を数えている日（UTC, YYYY-MM-DD）
    gen_count: int = 0


@dataclass
class Material:
    id: str
    title: str
    text: str
    due_date: datetime | None
    importance: int
    created_at: datetime
    files: list[FileData] = field(default_factory=list)
    generated: Generated | None = None
    fallback: Generated | None = None  # 生成に失敗したときに使う手書きの内容（サンプル教材用）
    attempts: list[Attempt] = field(default_factory=list)
    review_step: int | None = None
    next_review_at: datetime | None = None
    owner: str = ""  # 持ち主の uid
    published: bool = False  # 先生が公開中か
    source_id: str = ""  # 先生の教材からコピーした場合、元の教材ID
    shared_from: str = ""  # 同じく、先生の名前

    @property
    def mastery(self) -> float | None:
        """最新の事後テストの正答率。事後がなければ事前、どちらもなければ未測定。"""
        for kind in ("post", "pre"):
            for a in reversed(self.attempts):
                if a.kind == kind:
                    return a.accuracy
        return None


class MemoryStore:
    def __init__(self) -> None:
        self._items: dict[str, Material] = {}
        self._users: dict[str, User] = {}
        self._lock = threading.Lock()

    def add(self, **kwargs) -> Material:
        m = Material(id=uuid.uuid4().hex[:12], **kwargs)
        with self._lock:
            self._items[m.id] = m
        return m

    def get(self, material_id: str) -> Material | None:
        return self._items.get(material_id)

    def all(self, owner: str | None = None) -> list[Material]:
        items = [m for m in self._items.values() if owner is None or m.owner == owner]
        return sorted(items, key=lambda m: m.created_at)

    def delete(self, material_id: str) -> None:
        with self._lock:
            self._items.pop(material_id, None)

    def published(self) -> list[Material]:
        return sorted((m for m in self._items.values() if m.published), key=lambda m: m.created_at)

    def save(self, m: Material) -> None:
        """メモリ上では、Material を直接書き換えているので何もしない。"""

    def get_user(self, uid: str) -> User | None:
        return self._users.get(uid)

    def save_user(self, u: User) -> None:
        self._users[u.uid] = u

    def load_files(self, m: Material) -> list[FileData]:
        return m.files

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._users.clear()


# --- Datastore + Cloud Storage -------------------------------------------------

KIND = "Material"
USER_KIND = "User"
_NO_INDEX = ("title", "text", "files", "generated", "fallback", "attempts")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _dt(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s) if s else None


class DatastoreStore:
    """client / bucket は差し替え可能（テストでは偽物を渡す）。"""

    def __init__(self, client=None, bucket=None) -> None:
        if client is None:
            from google.cloud import datastore

            client = datastore.Client(project=os.environ.get("GOOGLE_CLOUD_PROJECT"))
        if bucket is None:
            from google.cloud import storage

            project = os.environ.get("GOOGLE_CLOUD_PROJECT")
            name = os.environ.get("STORAGE_BUCKET") or f"{project}.appspot.com"
            bucket = storage.Client(project=project).bucket(name)
        self.client = client
        self.bucket = bucket

    # 変換
    def _to_entity(self, m: Material):
        from google.cloud import datastore

        e = datastore.Entity(key=self.client.key(KIND, m.id), exclude_from_indexes=_NO_INDEX)
        e.update(
            {
                "title": m.title,
                "text": m.text,
                "due_date": m.due_date,
                "importance": m.importance,
                "created_at": m.created_at,
                "files": json.dumps([{"name": f.name, "mime": f.mime, "path": f.path} for f in m.files]),
                "generated": m.generated.model_dump_json() if m.generated else None,
                "fallback": m.fallback.model_dump_json() if m.fallback else None,
                "attempts": json.dumps([{"kind": a.kind, "accuracy": a.accuracy, "at": _iso(a.at)} for a in m.attempts]),
                "review_step": m.review_step,
                "next_review_at": m.next_review_at,
                "owner": m.owner,
                "published": m.published,
                "source_id": m.source_id,
                "shared_from": m.shared_from,
            }
        )
        return e

    @staticmethod
    def _from_entity(e) -> Material:
        return Material(
            id=e.key.name,
            title=e["title"],
            text=e["text"],
            due_date=e.get("due_date"),
            importance=e["importance"],
            created_at=e["created_at"],
            files=[FileData(name=f["name"], mime=f["mime"], path=f["path"]) for f in json.loads(e.get("files") or "[]")],
            generated=Generated.model_validate_json(e["generated"]) if e.get("generated") else None,
            fallback=Generated.model_validate_json(e["fallback"]) if e.get("fallback") else None,
            attempts=[Attempt(kind=a["kind"], accuracy=a["accuracy"], at=_dt(a["at"])) for a in json.loads(e.get("attempts") or "[]")],
            review_step=e.get("review_step"),
            next_review_at=e.get("next_review_at"),
            owner=e.get("owner", ""),
            published=bool(e.get("published", False)),
            source_id=e.get("source_id", ""),
            shared_from=e.get("shared_from", ""),
        )

    # 操作
    def add(self, **kwargs) -> Material:
        mid = uuid.uuid4().hex[:12]
        files: list[FileData] = kwargs.pop("files", []) or []
        stored: list[FileData] = []
        for i, f in enumerate(files):
            safe = re.sub(r"[^A-Za-z0-9._-]", "_", f.name)[:80] or "file"
            path = f"materials/{mid}/{i}_{safe}"
            self.bucket.blob(path).upload_from_string(f.data, content_type=f.mime)
            stored.append(FileData(name=f.name, mime=f.mime, path=path))
        m = Material(id=mid, files=stored, **kwargs)
        self.save(m)
        return m

    def save(self, m: Material) -> None:
        self.client.put(self._to_entity(m))

    def get(self, material_id: str) -> Material | None:
        e = self.client.get(self.client.key(KIND, material_id))
        return self._from_entity(e) if e is not None else None

    def all(self, owner: str | None = None) -> list[Material]:
        q = self.client.query(kind=KIND)
        if owner is not None:
            from google.cloud.datastore.query import PropertyFilter

            q.add_filter(filter=PropertyFilter("owner", "=", owner))
        items = [self._from_entity(e) for e in q.fetch()]
        return sorted(items, key=lambda m: m.created_at)

    def delete(self, material_id: str) -> None:
        """教材と、Cloud Storage 上のファイル本体を消す。"""
        m = self.get(material_id)
        if m is None:
            return
        for f in m.files:
            try:
                self.bucket.blob(f.path).delete()
            except Exception:  # すでに無い場合など。教材の削除は続ける
                pass
        self.client.delete_multi([self.client.key(KIND, material_id)])

    def published(self) -> list[Material]:
        from google.cloud.datastore.query import PropertyFilter

        q = self.client.query(kind=KIND)
        q.add_filter(filter=PropertyFilter("published", "=", True))
        return sorted((self._from_entity(e) for e in q.fetch()), key=lambda m: m.created_at)

    def get_user(self, uid: str) -> User | None:
        e = self.client.get(self.client.key(USER_KIND, uid))
        if e is None:
            return None
        return User(uid=uid, email=e.get("email", ""), name=e.get("name", ""), role=e.get("role"),
                    gen_date=e.get("gen_date", ""), gen_count=e.get("gen_count", 0))

    def save_user(self, u: User) -> None:
        from google.cloud import datastore

        e = datastore.Entity(key=self.client.key(USER_KIND, u.uid))
        e.update({"email": u.email, "name": u.name, "role": u.role, "gen_date": u.gen_date, "gen_count": u.gen_count})
        self.client.put(e)

    def load_files(self, m: Material) -> list[FileData]:
        """生成のときだけ、Cloud Storage からファイル本体を取り出す。"""
        return [FileData(name=f.name, mime=f.mime, data=self.bucket.blob(f.path).download_as_bytes(), path=f.path) for f in m.files]

    def clear(self) -> None:
        for kind in (KIND, USER_KIND):
            keys = [e.key for e in self.client.query(kind=kind).fetch()]
            if keys:
                self.client.delete_multi(keys)


def make_store():
    """STORE_BACKEND=datastore なら Datastore、それ以外はメモリ。"""
    if os.environ.get("STORE_BACKEND", "memory").lower() == "datastore":
        return DatastoreStore()
    return MemoryStore()
