"""DatastoreStore を、偽の Datastore / Cloud Storage で試す（実際の通信はしない）。"""

from datetime import datetime, timezone

from google.cloud import datastore

from schemas import Generated, QuizQuestion
from store import Attempt, DatastoreStore, FileData


class FakeQuery:
    def __init__(self, items):
        self._items = items
        self._filters = []

    def add_filter(self, filter):
        self._filters.append(filter)

    def fetch(self):
        out = list(self._items.values())
        for f in self._filters:
            out = [e for e in out if e.get(f.property_name) == f.value]
        return out


class FakeClient:
    def __init__(self):
        self.items = {}

    def key(self, kind, name):
        return datastore.Key(kind, name, project="test")

    def put(self, e):
        self.items[(e.key.kind, e.key.name)] = e

    def get(self, key):
        return self.items.get((key.kind, key.name))

    def query(self, kind):
        return FakeQuery({k: v for k, v in self.items.items() if k[0] == kind})

    def delete_multi(self, keys):
        for k in keys:
            self.items.pop((k.kind, k.name), None)


class FakeBlob:
    def __init__(self, blobs, name):
        self._blobs, self._name = blobs, name

    def upload_from_string(self, data, content_type=None):
        self._blobs[self._name] = data

    def download_as_bytes(self):
        return self._blobs[self._name]

    def delete(self):
        del self._blobs[self._name]


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def blob(self, name):
        return FakeBlob(self.blobs, name)


def _store():
    return DatastoreStore(client=FakeClient(), bucket=FakeBucket())


def _add(s, **kw):
    return s.add(
        title="二次関数",
        text="本文" * 1000,  # 1500バイト超でも保存できること（索引なし）
        due_date=datetime(2026, 11, 20, tzinfo=timezone.utc),
        importance=4,
        created_at=datetime(2026, 11, 7, tzinfo=timezone.utc),
        **kw,
    )


def test_roundtrip_all_fields():
    s = _store()
    gen = Generated(summary=["要点"], questions=[QuizQuestion(question="Q", choices=["a", "b"], answer_index=1, explanation="e")], source="vertex")
    m = _add(s, fallback=gen)
    m.generated = gen
    m.attempts.append(Attempt(kind="post", accuracy=0.5, at=datetime(2026, 11, 7, 1, tzinfo=timezone.utc)))
    m.review_step = 1
    m.next_review_at = datetime(2026, 11, 10, tzinfo=timezone.utc)
    s.save(m)

    got = s.get(m.id)
    assert got.title == "二次関数" and got.text == "本文" * 1000 and got.importance == 4
    assert got.generated == gen and got.fallback == gen
    assert got.attempts[0].accuracy == 0.5 and got.mastery == 0.5
    assert got.review_step == 1 and got.next_review_at == datetime(2026, 11, 10, tzinfo=timezone.utc)


def test_files_go_to_bucket_and_load_back():
    s = _store()
    m = _add(s, files=[FileData(name="ノート 1.pdf", mime="application/pdf", data=b"%PDF-data")])
    got = s.get(m.id)
    assert got.files[0].name == "ノート 1.pdf" and got.files[0].data == b""  # 一覧・取得では本体を読まない
    assert list(s.bucket.blobs.values()) == [b"%PDF-data"]
    loaded = s.load_files(got)
    assert loaded[0].data == b"%PDF-data" and loaded[0].mime == "application/pdf"


def test_all_sorted_get_missing_and_clear():
    s = _store()
    a = _add(s)
    assert s.get("nope") is None
    assert [m.id for m in s.all()] == [a.id]
    s.clear()
    assert s.all() == []


def test_api_flow_persists_with_datastore(monkeypatch):
    """API の一連の流れ（登録→生成→採点→復習）が、Datastore でも同じように動く。"""
    from fastapi.testclient import TestClient

    import main

    monkeypatch.setenv("GEMINI_BACKEND", "dummy")
    s = _store()
    monkeypatch.setattr(main, "store", s)
    c = TestClient(main.app)
    mid = c.post("/materials", json={"title": "t", "text": "文1。文2。文3。文4。"}).json()["id"]
    c.post(f"/materials/{mid}/generate")
    assert s.get(mid).generated is not None  # 保存されている
    n = len(c.get(f"/materials/{mid}/quiz").json()["questions"])
    correct = c.post(f"/materials/{mid}/answers", json={"kind": "pre", "answers": [0] * n}).json()["correct_indexes"]
    r = c.post(f"/materials/{mid}/answers", json={"kind": "post", "answers": correct}).json()
    assert r["review_step"] is not None
    assert s.get(mid).next_review_at is not None and len(s.get(mid).attempts) == 2
    assert c.get("/review").json()[0]["due"] is False

    up = c.post("/materials/upload", data={"title": "pdf"}, files={"files": ("a.pdf", b"%PDF-1", "application/pdf")}).json()
    assert s.load_files(s.get(up["id"]))[0].data == b"%PDF-1"


def test_owner_filter_and_user_roundtrip():
    from store import User

    s = _store()
    a = _add(s, owner="u1")
    _add(s, owner="u2")
    assert [m.id for m in s.all(owner="u1")] == [a.id] and len(s.all()) == 2
    assert s.get(a.id).owner == "u1"
    assert s.get_user("u1") is None
    s.save_user(User(uid="u1", email="a@b", name="太郎", role="teacher", gen_date="2026-11-07", gen_count=3))
    u = s.get_user("u1")
    assert (u.email, u.name, u.role, u.gen_date, u.gen_count) == ("a@b", "太郎", "teacher", "2026-11-07", 3)


def test_published_and_copy_fields_roundtrip():
    s = _store()
    a = _add(s, owner="t")
    b = _add(s, owner="t")
    a.published = True
    s.save(a)
    c = _add(s, owner="stu", source_id=a.id, shared_from="先生")
    assert [m.id for m in s.published()] == [a.id] and b.id not in [m.id for m in s.published()]
    got = s.get(c.id)
    assert got.source_id == a.id and got.shared_from == "先生" and got.published is False


def test_delete_removes_entity_and_files():
    s = _store()
    m = _add(s, owner="u1", files=[FileData(name="a.pdf", mime="application/pdf", data=b"x")])
    other = _add(s, owner="u1")
    assert len(s.bucket.blobs) == 1
    s.delete(m.id)
    assert s.get(m.id) is None and s.bucket.blobs == {}
    assert [x.id for x in s.all()] == [other.id]
    s.delete("nope")  # 無いIDでも落ちない
