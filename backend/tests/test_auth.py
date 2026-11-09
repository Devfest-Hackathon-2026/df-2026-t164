"""ログイン確認・持ち主ごとの分離・登録上限のテスト。"""

import pytest
from fastapi.testclient import TestClient

import auth
import main

TEXT = "二次関数のグラフは放物線になる。頂点は平方完成で求められる。最大値と最小値は定義域で決まる。"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("GEMINI_BACKEND", "dummy")
    monkeypatch.setenv("AUTH_BACKEND", "firebase")
    main.store.clear()

    def fake_verify(token: str) -> auth.Identity:
        if token.startswith("valid-"):
            uid = token[len("valid-"):]
            return auth.Identity(uid=uid, email=f"{uid}@example.com", name=uid)
        raise auth.AuthError("bad token")

    monkeypatch.setattr(auth, "verify_token", fake_verify)


@pytest.fixture
def client():
    return TestClient(main.app)


def H(uid="alice"):
    return {"Authorization": f"Bearer valid-{uid}"}


def _create(client, uid="alice"):
    r = client.post("/materials", json={"title": "t", "text": TEXT}, headers=H(uid))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_requires_login(client):
    assert client.get("/materials").status_code == 401
    assert client.get("/materials", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get("/materials", headers={"Authorization": "Basic xx"}).status_code == 401
    assert client.get("/health").status_code == 200  # ログイン不要


def test_materials_are_private_per_user(client):
    mid = _create(client, "alice")
    assert [m["id"] for m in client.get("/materials", headers=H("alice")).json()] == [mid]
    assert client.get("/materials", headers=H("bob")).json() == []
    for path in ("", "/summary", "/quiz"):
        assert client.get(f"/materials/{mid}{path}", headers=H("bob")).status_code == 404
    assert client.post(f"/materials/{mid}/generate", headers=H("bob")).status_code == 404
    assert client.post(f"/materials/{mid}/answers", json={"answers": [0]}, headers=H("bob")).status_code == 404
    assert client.get("/review", headers=H("bob")).json() == []
    assert len(client.get("/review", headers=H("alice")).json()) == 1


def test_role_is_chosen_once(client):
    me = client.get("/me", headers=H()).json()
    assert me["role"] is None and me["uid"] == "alice" and me["email"] == "alice@example.com"
    r = client.post("/me/role", json={"role": "teacher"}, headers=H())
    assert r.status_code == 200 and r.json()["role"] == "teacher"
    assert client.post("/me/role", json={"role": "student"}, headers=H()).status_code == 409
    assert client.get("/me", headers=H()).json()["role"] == "teacher"
    assert client.post("/me/role", json={"role": "admin"}, headers=H("bob")).status_code == 422
    assert client.get("/me", headers=H("bob")).json()["role"] is None  # 他の人には影響しない


def test_material_limit_per_user(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_MATERIALS", 2)
    _create(client, "alice")
    _create(client, "alice")
    r = client.post("/materials", json={"title": "t", "text": TEXT}, headers=H("alice"))
    assert r.status_code == 429
    assert client.post("/materials/sample", headers=H("alice")).status_code == 429
    up = client.post("/materials/upload", data={"title": "x", "text": TEXT}, headers=H("alice"))
    assert up.status_code == 429
    _create(client, "bob")  # 他の人は影響を受けない
    me = client.get("/me", headers=H("alice")).json()
    assert me["materials_used"] == 2 and me["materials_limit"] == 2


def test_generation_limit_per_day(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_GENERATIONS_PER_DAY", 2)
    ids = [_create(client) for _ in range(3)]
    assert client.post(f"/materials/{ids[0]}/generate", headers=H()).status_code == 200
    assert client.post(f"/materials/{ids[0]}/generate", headers=H()).status_code == 200  # 再利用は数えない
    assert client.post(f"/materials/{ids[1]}/generate", headers=H()).status_code == 200
    assert client.post(f"/materials/{ids[2]}/generate", headers=H()).status_code == 429
    assert client.post(f"/materials/{ids[0]}/generate?regenerate=true", headers=H()).status_code == 429
    assert client.get("/me", headers=H()).json()["generations_today"] == 2
    # 他の人は別枠
    other = _create(client, "bob")
    assert client.post(f"/materials/{other}/generate", headers=H("bob")).status_code == 200


def test_generation_count_resets_next_day(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_GENERATIONS_PER_DAY", 1)
    a, b = _create(client), _create(client)
    assert client.post(f"/materials/{a}/generate", headers=H()).status_code == 200
    assert client.post(f"/materials/{b}/generate", headers=H()).status_code == 429
    u = main.store.get_user("alice")
    u.gen_date = "2000-01-01"  # 昨日以前のカウントは無効
    main.store.save_user(u)
    assert client.post(f"/materials/{b}/generate", headers=H()).status_code == 200


def test_no_auth_mode_uses_dev_user(monkeypatch):
    monkeypatch.setenv("AUTH_BACKEND", "none")
    c = TestClient(main.app)
    assert c.get("/me").json()["uid"] == "dev-user"
