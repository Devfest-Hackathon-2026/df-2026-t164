import os
import pytest
from fastapi.testclient import TestClient

import generator
import main

TEXT = (
    "二次関数のグラフは放物線になる。"
    "頂点は平方完成で求められる。"
    "最大値と最小値は定義域によって決まる。"
    "判別式が正のとき、x軸と2点で交わる。"
)


@pytest.fixture(autouse=True)
def _dummy_backend(monkeypatch):
    # テストでは外部サービスを呼ばない
    monkeypatch.setenv("GEMINI_BACKEND", "dummy")
    main.store.clear()


@pytest.fixture
def client():
    return TestClient(main.app)


def _create(client, **kw):
    body = {"title": "二次関数", "text": TEXT, **kw}
    r = client.post("/materials", json=body)
    assert r.status_code == 201
    return r.json()["id"]


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["generator"] == "dummy"


def test_full_flow(client):
    mid = _create(client, importance=4)

    # 生成前はクイズ・要点が取れない
    assert client.get(f"/materials/{mid}/quiz").status_code == 409

    g = client.post(f"/materials/{mid}/generate")
    assert g.status_code == 200 and len(g.json()["summary"]) >= 1

    quiz = client.get(f"/materials/{mid}/quiz").json()
    assert len(quiz["questions"]) == 3
    assert "answer_index" not in quiz["questions"][0]  # 正解は学習者に見せない

    # 事前テスト：復習予定は動かさない
    pre = client.post(f"/materials/{mid}/answers", json={"kind": "pre", "answers": [0, 0, 0]}).json()
    assert pre["review_step"] is None and pre["next_review_at"] is None

    # 事後テスト：全問正解にして復習ステップが進むこと
    correct = pre["correct_indexes"]
    post = client.post(f"/materials/{mid}/answers", json={"kind": "post", "answers": correct}).json()
    assert post["accuracy"] == 1.0 and all(post["results"])
    assert post["review_step"] == 1 and post["next_review_at"] is not None

    m = client.get(f"/materials/{mid}").json()
    assert m["mastery"] == 1.0 and m["generated"] is True


def test_generate_is_reused(client):
    mid = _create(client)
    client.post(f"/materials/{mid}/generate")
    first = main.store.get(mid).generated
    client.post(f"/materials/{mid}/generate")
    assert main.store.get(mid).generated is first  # 再解析しない
    client.post(f"/materials/{mid}/generate?regenerate=true")
    assert main.store.get(mid).generated is not first


def test_review_list_puts_weak_material_first(client):
    weak, strong = _create(client, title="弱い"), _create(client, title="強い")
    for mid in (weak, strong):
        client.post(f"/materials/{mid}/generate")
    n = len(client.get(f"/materials/{strong}/quiz").json()["questions"])
    correct = client.post(
        f"/materials/{strong}/answers", json={"kind": "post", "answers": [0] * n}
    ).json()["correct_indexes"]
    client.post(f"/materials/{strong}/answers", json={"kind": "post", "answers": correct})
    client.post(f"/materials/{weak}/answers", json={"kind": "post", "answers": [9] * n})

    review = client.get("/review").json()
    assert [i["title"] for i in review] == ["弱い", "強い"]
    assert review[0]["score"] > review[1]["score"]
    assert review[0]["reason"]


def test_unmeasured_material_in_review_list(client):
    _create(client)
    item = client.get("/review").json()[0]
    assert item["mastery"] is None and "測っていません" in item["reason"]


def test_errors(client):
    assert client.get("/materials/nope").status_code == 404
    assert client.post("/materials", json={"title": "", "text": "x"}).status_code == 422
    mid = _create(client)
    client.post(f"/materials/{mid}/generate")
    too_many = client.post(f"/materials/{mid}/answers", json={"answers": [0] * 10})
    assert too_many.status_code == 422


def test_resolve_backend(monkeypatch):
    monkeypatch.delenv("GEMINI_BACKEND", raising=False)
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert generator.resolve_backend() == "dummy"
    monkeypatch.setenv("GEMINI_API_KEY", "x")
    assert generator.resolve_backend() == "aistudio"
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    assert generator.resolve_backend() == "vertex"
    monkeypatch.setenv("GEMINI_BACKEND", "dummy")
    assert generator.resolve_backend() == "dummy"


def test_gemini_failure_falls_back_to_dummy(monkeypatch):
    monkeypatch.setenv("GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")

    def boom(*a, **k):
        raise RuntimeError("quota")

    monkeypatch.setattr(generator, "generate_gemini", boom)
    g = generator.generate("題", TEXT)
    assert g.source == "dummy-fallback" and g.questions


# ---- ファイルアップロード -------------------------------------------------

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


def _upload(client, files, **data):
    payload = {"title": "ノートの写真", **data}
    return client.post("/materials/upload", data=payload, files=files)


def test_upload_image_and_generate(client):
    r = _upload(client, [("files", ("note.png", PNG, "image/png"))])
    assert r.status_code == 201
    body = r.json()
    assert body["file_names"] == ["note.png"]
    assert client.post(f"/materials/{body['id']}/generate").status_code == 200  # dummy でも生成できる
    assert main.store.get(body["id"]).files[0].data == PNG


def test_upload_text_only_and_multiple_files(client):
    assert _upload(client, [], text="本文だけの教材です。").status_code == 201
    two = [("files", ("a.png", PNG, "image/png")), ("files", ("b.pdf", b"%PDF-1.4 x", "application/pdf"))]
    r = _upload(client, two, importance="5")
    assert r.status_code == 201 and r.json()["file_names"] == ["a.png", "b.pdf"]


def test_upload_rejects_bad_input(client):
    assert _upload(client, []).status_code == 422  # 本文もファイルもない
    bad = _upload(client, [("files", ("x.exe", b"MZ", "application/octet-stream"))])
    assert bad.status_code == 415
    empty = _upload(client, [("files", ("e.png", b"", "image/png"))])
    assert empty.status_code == 422
    many = [("files", (f"{i}.png", PNG, "image/png")) for i in range(main.MAX_FILES + 1)]
    assert _upload(client, many).status_code == 422


def test_upload_rejects_too_large(client, monkeypatch):
    monkeypatch.setattr(main, "MAX_FILE_BYTES", 10)
    r = _upload(client, [("files", ("big.png", PNG, "image/png"))])
    assert r.status_code == 413


def test_gemini_receives_files_as_parts(monkeypatch):
    """Gemini には本文のあとにファイルが Part として渡される。"""
    from store import FileData

    captured = {}

    class FakeModels:
        def generate_content(self, model, contents, config):
            captured["contents"] = contents

            class R:
                parsed = generator._GeminiOut(
                    summary=["要点"],
                    questions=[
                        generator._GeminiOut.Question(
                            question="q",
                            choices=["a", "b"],
                            answer_index=0,
                            evidence="添付された教材の内容です。",
                        )
                    ],
                )
                text = ""

            return R()

    class FakeClient:
        models = FakeModels()

    monkeypatch.setattr(generator, "_client", lambda backend: FakeClient())
    files = [FileData(name="n.png", mime="image/png", data=PNG), FileData(name="d.pdf", mime="application/pdf", data=b"%PDF")]
    g = generator.generate_gemini("題", "", "vertex", files)
    assert g.source == "vertex"
    parts = captured["contents"]
    assert len(parts) == 3 and "本文なし" in parts[0]
    assert [p.inline_data.mime_type for p in parts[1:]] == ["image/png", "application/pdf"]


# ---- サンプル教材・今日の復習 -------------------------------------------------

def test_sample_material_uses_handwritten_fallback_without_gemini(client):
    r = client.post("/materials/sample")
    assert r.status_code == 201
    m = r.json()
    assert "サンプル" in m["title"] and m["due_date"] is not None and m["importance"] == 4
    g = client.post(f"/materials/{m['id']}/generate").json()
    assert g["source"] == "dummy-fallback"  # dummy 環境 → 手書きの内容になる
    assert "放物線" in g["summary"][0]
    assert len(client.get(f"/materials/{m['id']}/quiz").json()["questions"]) == 3


def test_sample_falls_back_when_gemini_fails(client, monkeypatch):
    monkeypatch.setenv("GEMINI_BACKEND", "vertex")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "p")
    monkeypatch.setattr(generator, "generate_gemini", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    mid = client.post("/materials/sample").json()["id"]
    g = client.post(f"/materials/{mid}/generate").json()
    assert "放物線" in g["summary"][0]  # 通常の教材なら機械的な代用生成になるが、サンプルは手書き内容


def test_normal_material_is_not_replaced_by_sample_fallback(client):
    mid = _create(client)
    client.post(f"/materials/{mid}/generate")
    assert main.store.get(mid).generated.source == "dummy"


def test_review_due_flag(client):
    mid = _create(client)
    assert client.get("/review").json()[0]["due"] is True  # 未学習
    client.post(f"/materials/{mid}/generate")
    n = len(client.get(f"/materials/{mid}/quiz").json()["questions"])
    correct = client.post(f"/materials/{mid}/answers", json={"kind": "pre", "answers": [0] * n}).json()["correct_indexes"]
    assert client.get("/review").json()[0]["due"] is True  # 事前だけでは予定なし → 今日の対象
    client.post(f"/materials/{mid}/answers", json={"kind": "post", "answers": correct})
    assert client.get("/review").json()[0]["due"] is False  # 事後を受けたので次回は先


def test_low_mastery_stays_due_today(client):
    mid = _create(client)
    client.post(f"/materials/{mid}/generate")
    n = len(client.get(f"/materials/{mid}/quiz").json()["questions"])
    correct = client.post(f"/materials/{mid}/answers", json={"kind": "pre", "answers": [0] * n}).json()["correct_indexes"]
    wrong = [(c + 1) % 4 for c in correct]
    client.post(f"/materials/{mid}/answers", json={"kind": "post", "answers": wrong})
    assert client.get("/review").json()[0]["due"] is True  # 0%なので当日も残る
    client.post(f"/materials/{mid}/answers", json={"kind": "post", "answers": correct})
    assert client.get("/review").json()[0]["due"] is False  # 理解できたので外れる


def test_serves_built_frontend(tmp_path):
    """frontend/dist 相当のフォルダがあれば、API と同じサービスから配信される。"""
    import importlib

    (tmp_path / "index.html").write_text("<html>SchoolRestart UI</html>", encoding="utf-8")
    os.environ["FRONTEND_DIST"] = str(tmp_path)
    try:
        reloaded = importlib.reload(main)
        c = TestClient(reloaded.app)
        assert "SchoolRestart UI" in c.get("/").text
        assert c.get("/health").json()["status"] == "ok"  # API が優先される
    finally:
        del os.environ["FRONTEND_DIST"]
        importlib.reload(main)
