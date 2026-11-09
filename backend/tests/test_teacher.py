"""先生の流れ（編集・公開）と、生徒への共有のテスト。"""

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
    monkeypatch.setattr(
        auth,
        "verify_token",
        lambda t: auth.Identity(uid=t.removeprefix("valid-"), email=f"{t[6:]}@example.com", name=t[6:]),
    )


@pytest.fixture
def client():
    return TestClient(main.app)


def H(uid):
    return {"Authorization": f"Bearer valid-{uid}"}


def _login(client, uid, role):
    client.post("/me/role", json={"role": role}, headers=H(uid))


def _teacher_material(client, generate=True):
    _login(client, "teacher", "teacher")
    mid = client.post("/materials", json={"title": "二次関数", "text": TEXT}, headers=H("teacher")).json()["id"]
    if generate:
        client.post(f"/materials/{mid}/generate", headers=H("teacher"))
    return mid


EDIT = {
    "summary": ["  頂点は平方完成で求める  ", "最大値は定義域で決まる"],
    "questions": [
        {"question": "放物線の頂点を求める方法は？", "choices": ["平方完成", "因数分解", "微分"], "answer_index": 0, "explanation": "平方完成で頂点が分かる"},
    ],
}


def test_get_and_edit_content(client):
    mid = _teacher_material(client)
    c = client.get(f"/materials/{mid}/content", headers=H("teacher")).json()
    assert c["questions"][0]["answer_index"] in range(len(c["questions"][0]["choices"]))
    r = client.put(f"/materials/{mid}/content", json=EDIT, headers=H("teacher"))
    assert r.status_code == 200
    got = client.get(f"/materials/{mid}/content", headers=H("teacher")).json()
    assert got["source"] == "teacher" and got["summary"][0] == "頂点は平方完成で求める"  # 前後の空白は除く
    assert len(got["questions"]) == 1 and got["questions"][0]["choices"] == ["平方完成", "因数分解", "微分"]
    # 学習用のクイズにも反映（正解は含まれない）
    q = client.get(f"/materials/{mid}/quiz", headers=H("teacher")).json()["questions"]
    assert q == [{"question": "放物線の頂点を求める方法は？", "choices": ["平方完成", "因数分解", "微分"]}]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda b: b.update(summary=[]),
        lambda b: b.update(summary=["  "]),
        lambda b: b.update(questions=[]),
        lambda b: b["questions"][0].update(answer_index=3),
        lambda b: b["questions"][0].update(answer_index=-1),
        lambda b: b["questions"][0].update(choices=["だけ"]),
        lambda b: b["questions"][0].update(choices=["a", " "]),
        lambda b: b["questions"][0].update(question=" "),
    ],
)
def test_invalid_edit_is_rejected(client, mutate):
    import copy

    mid = _teacher_material(client)
    body = copy.deepcopy(EDIT)
    mutate(body)
    assert client.put(f"/materials/{mid}/content", json=body, headers=H("teacher")).status_code == 422


def test_students_cannot_edit_or_publish_or_see_answers(client):
    mid = _teacher_material(client)
    _login(client, "stu", "student")
    smid = client.post("/materials", json={"title": "s", "text": TEXT}, headers=H("stu")).json()["id"]
    client.post(f"/materials/{smid}/generate", headers=H("stu"))
    for call in (
        lambda: client.get(f"/materials/{smid}/content", headers=H("stu")),
        lambda: client.put(f"/materials/{smid}/content", json=EDIT, headers=H("stu")),
        lambda: client.post(f"/materials/{smid}/publish", headers=H("stu")),
        lambda: client.post(f"/materials/{smid}/unpublish", headers=H("stu")),
    ):
        assert call().status_code == 403
    # 他人の教材（先生のもの）は、先生でも触れない
    _login(client, "teacher2", "teacher")
    assert client.put(f"/materials/{mid}/content", json=EDIT, headers=H("teacher2")).status_code == 404
    assert client.post(f"/materials/{mid}/publish", headers=H("teacher2")).status_code == 404


def test_cannot_edit_or_publish_before_generation(client):
    mid = _teacher_material(client, generate=False)
    assert client.get(f"/materials/{mid}/content", headers=H("teacher")).status_code == 409
    assert client.put(f"/materials/{mid}/content", json=EDIT, headers=H("teacher")).status_code == 409
    assert client.post(f"/materials/{mid}/publish", headers=H("teacher")).status_code == 409


def test_publish_share_and_copy_flow(client):
    mid = _teacher_material(client)
    client.put(f"/materials/{mid}/content", json=EDIT, headers=H("teacher"))
    _login(client, "stu", "student")
    assert client.get("/shared", headers=H("stu")).json() == []  # 未公開は見えない
    assert client.post(f"/shared/{mid}/add", headers=H("stu")).status_code == 404

    pub = client.post(f"/materials/{mid}/publish", headers=H("teacher")).json()
    assert pub["published"] is True
    shared = client.get("/shared", headers=H("stu")).json()
    assert [(s["id"], s["teacher_name"], s["added"]) for s in shared] == [(mid, "teacher", False)]
    assert client.get("/shared", headers=H("teacher")).json() == []  # 自分の教材は含めない

    r = client.post(f"/shared/{mid}/add", headers=H("stu"))
    assert r.status_code == 201
    mine = r.json()
    assert mine["shared_from"] == "teacher" and mine["generated"] is True and mine["published"] is False
    assert mine["id"] != mid
    # 2回押しても増えない
    assert client.post(f"/shared/{mid}/add", headers=H("stu")).json()["id"] == mine["id"]
    assert len(client.get("/materials", headers=H("stu")).json()) == 1
    assert client.get("/shared", headers=H("stu")).json()[0]["my_material_id"] == mine["id"]

    # 自分用のコピーで学べる。成績は生徒だけのもの
    quiz = client.get(f"/materials/{mine['id']}/quiz", headers=H("stu")).json()["questions"]
    assert len(quiz) == 1
    res = client.post(f"/materials/{mine['id']}/answers", json={"kind": "post", "answers": [0]}, headers=H("stu")).json()
    assert res["accuracy"] == 1.0 and res["correct_indexes"] == [0]
    assert client.get(f"/materials/{mid}", headers=H("teacher")).json()["mastery"] is None
    assert client.get(f"/materials/{mine['id']}/summary", headers=H("stu")).json()["source"] == "teacher"

    # コピーは作り直せない（先生の内容を上書きしない）。生成回数も使わない
    assert client.post(f"/materials/{mine['id']}/generate?regenerate=true", headers=H("stu")).status_code == 409
    assert client.get("/me", headers=H("stu")).json()["generations_today"] == 0

    # 公開を取り下げると新規には見えなくなるが、コピー済みの分は使える
    client.post(f"/materials/{mid}/unpublish", headers=H("teacher"))
    assert client.get("/shared", headers=H("stu")).json() == []
    assert client.get(f"/materials/{mine['id']}/quiz", headers=H("stu")).status_code == 200


def test_edit_after_copy_does_not_change_students_copy(client):
    mid = _teacher_material(client)
    client.post(f"/materials/{mid}/publish", headers=H("teacher"))
    _login(client, "stu", "student")
    mine = client.post(f"/shared/{mid}/add", headers=H("stu")).json()["id"]
    before = client.get(f"/materials/{mine}/summary", headers=H("stu")).json()["summary"]
    client.put(f"/materials/{mid}/content", json=EDIT, headers=H("teacher"))
    assert client.get(f"/materials/{mine}/summary", headers=H("stu")).json()["summary"] == before


def test_copy_counts_toward_material_limit(client, monkeypatch):
    mid = _teacher_material(client)
    client.post(f"/materials/{mid}/publish", headers=H("teacher"))
    _login(client, "stu", "student")
    monkeypatch.setattr(main, "MAX_MATERIALS", 1)
    client.post("/materials", json={"title": "s", "text": TEXT}, headers=H("stu"))
    assert client.post(f"/shared/{mid}/add", headers=H("stu")).status_code == 429


def test_owner_can_delete_own_material(client):
    _login(client, "stu", "student")
    mid = client.post("/materials", json={"title": "s", "text": TEXT}, headers=H("stu")).json()["id"]
    assert client.delete(f"/materials/{mid}", headers=H("stu")).status_code == 204
    assert client.get(f"/materials/{mid}", headers=H("stu")).status_code == 404
    assert client.get("/materials", headers=H("stu")).json() == []
    assert client.get("/me", headers=H("stu")).json()["materials_used"] == 0  # 枠も空く
    assert client.delete(f"/materials/{mid}", headers=H("stu")).status_code == 404  # 2回目


def test_cannot_delete_others_material(client):
    mid = _teacher_material(client)
    _login(client, "stu", "student")
    assert client.delete(f"/materials/{mid}", headers=H("stu")).status_code == 404
    assert client.get(f"/materials/{mid}", headers=H("teacher")).status_code == 200


def test_teacher_delete_keeps_students_copy_and_hides_from_shared(client):
    mid = _teacher_material(client)
    client.post(f"/materials/{mid}/publish", headers=H("teacher"))
    _login(client, "stu", "student")
    mine = client.post(f"/shared/{mid}/add", headers=H("stu")).json()["id"]
    assert client.delete(f"/materials/{mid}", headers=H("teacher")).status_code == 204
    assert client.get("/shared", headers=H("stu")).json() == []
    assert client.post(f"/shared/{mid}/add", headers=H("stu")).status_code == 404  # 元が無いので、新たには追加できない
    assert [m["id"] for m in client.get("/materials", headers=H("stu")).json()] == [mine]  # 手元のコピーは残る
    assert client.get(f"/materials/{mine}/quiz", headers=H("stu")).status_code == 200
    assert client.delete(f"/materials/{mine}", headers=H("stu")).status_code == 204


def test_name_is_filled_in_later(client, monkeypatch):
    """メール登録は、アカウント作成の直後に名前を設定する。最初の呼び出しで名前が空でも、あとで補う。"""
    monkeypatch.setattr(auth, "verify_token", lambda t: auth.Identity(uid="x", email="x@example.com", name=""))
    assert client.get("/me", headers=H("x")).json()["name"] == ""
    monkeypatch.setattr(auth, "verify_token", lambda t: auth.Identity(uid="x", email="x@example.com", name="花子"))
    assert client.get("/me", headers=H("x")).json()["name"] == "花子"
