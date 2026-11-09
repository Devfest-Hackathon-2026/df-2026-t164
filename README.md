# SchoolRestart
欠席した授業を短時間で学び直せるAI学習支援（GDGoC Japan Hackathon 2026／チーム164）

## 概要
病気やインフルエンザによる出席停止などで、数日〜数週間欠席した小・中・高校生が、欠席した分の授業を短時間で学び直すためのアプリです。

- 先生が教材（PDF / 画像 / テキスト）を登録すると、Vertex AI（Gemini）が要点3点と4択クイズ3問を生成します
- 生成されたクイズは、答えの根拠が教材本文に実在するかを照合し、通過したものだけを表示します（根拠が確認できない場合は再生成し、それでも満たなければ代替生成に切り替えます）
- 学習の優先度スコア（理解不足40%／期限の近さ30%／復習の必要性20%／教材の重要度10%）と復習間隔（1・3・7・14日）で、学び直しの順番を支援します
- 先生は生成された要点・クイズを確認・編集して生徒に公開でき、生徒はそれを自分用にコピーして学びます

## デプロイURL
https://project-b136cb29-e39c-4cf1-a95.an.r.appspot.com

## 技術構成
- フロントエンド: React + TypeScript + Vite + Tailwind CSS
- バックエンド: FastAPI（Python）。App Engine 上でフロントエンドと同一オリジンで配信
- AI生成: Vertex AI（Gemini）
- データ保存: Firestore（Datastore モード）／ファイル保存: Cloud Storage
- 認証: Firebase Authentication（Google ログイン／メールアドレス＋パスワード）

## バックエンド（backend/）の起動
```
cd backend
python -m venv .venv
.venv\Scripts\activate        # Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload      # http://localhost:8000/docs でAPIを試せる
pytest                         # テスト
```
- 生成方式は環境変数 `GEMINI_BACKEND`（vertex / aistudio / dummy）で切り替え。キーが無ければ dummy で動く。変数名は `.env.example` を参照（値は書かない）。
- Vertex AI をローカルで使う場合: `gcloud auth application-default login` のあと `GOOGLE_CLOUD_PROJECT` を設定。
- 保存先は環境変数 `STORE_BACKEND` で切り替える（本番は Datastore。詳細は後述の「保存先」節）。

## フロントエンド（frontend/）の起動
```
cd frontend
npm install
npm run dev     # http://localhost:5173 （先にバックエンドを起動しておく）
npm run build   # 型チェック + ビルド
```
- API の接続先は `VITE_API_BASE`（既定: http://localhost:8000）。

## PDF・画像による教材登録
- `POST /materials/upload`（multipart）。PDF / PNG / JPEG / WebP、1ファイル10MBまで、最大5ファイル。本文は任意。
- 生成時に Gemini（Vertex AI）へファイルをそのまま渡す。`GEMINI_BACKEND=dummy` ではファイルの中身は読まれない。
- ファイル本体は Cloud Storage に保存する（`STORE_BACKEND=datastore` のとき。未設定のローカル・テストではメモリ上に保持）。

## App Engine へのデプロイ（バックエンドがフロントも配信）
- 1サービス構成。`backend/main.py` が `frontend/dist` を同じオリジンで配信する（`frontend/dist` がある時だけ）。
- 手順（共有GCPプロジェクトを触るので、実行前に Discord で宣言する）:
  1. `cd frontend && npm install && npm run build`
  2. リポジトリのルートで `gcloud app deploy app.yaml --project project-b136cb29-e39c-4cf1-a95`
- 初回のみ: App Engine アプリの作成（リージョン決定）が必要。管理担当と相談する。
- App Engine の実行用サービスアカウントに Vertex AI を呼ぶ権限（`roles/aiplatform.user`）が必要。
- 保存先が Datastore のため複数インスタンスでデータは共有される。`automatic_scaling.max_instances` は課金が増えすぎないよう 3 に制限している。
- 公開URLは 11/14 の地域大会まで残すこと。

## 保存先（Firestore Datastore モード + Cloud Storage）
- 環境変数 `STORE_BACKEND=datastore` で、教材の本文・成績は Firestore（Datastore モード）、PDF・画像は Cloud Storage に保存する。未設定ならメモリ（ローカル・テスト用）。
- App Engine では `app.yaml` で有効化済み。実行用サービスアカウントに `roles/datastore.user` が必要。
- ローカルで試すときは `gcloud auth application-default login` のあと `STORE_BACKEND=datastore` と `GOOGLE_CLOUD_PROJECT` を設定する（共有プロジェクトに書き込むので注意）。

## ログインと上限（バックエンド）
- `AUTH_BACKEND=firebase` のとき、`Authorization: Bearer <FirebaseのIDトークン>` をサーバーで検証する。無ければ 401。未設定（none）の間は固定の開発ユーザーで動く。
- 教材は持ち主ごとに分かれ、他人の教材は 404。`GET /me` で自分の情報と使用量、`POST /me/role` で先生/生徒を選ぶ（最初の1回のみ、あとから変更不可）。
- 上限は 1人あたり 教材20件・生成1日30回（UTC の日付で数える）・ファイル1つ10MB。超えると 429。値は `backend/main.py` の `MAX_MATERIALS` / `MAX_GENERATIONS_PER_DAY`。
- 画面は Google ログイン（Firebase）。設定値は `frontend/src/firebase.ts`（公開前提の値）。ローカル開発でも、画面ではログインが必要（`localhost` が Firebase の承認済みドメインに入っていること）。
- `app.yaml` では `AUTH_BACKEND=firebase` を有効化済み。

## 先生の流れ（確認・編集・公開）
- 先生は教材を登録・生成したあと、要点とクイズ（文章・選択肢・正解・解説）を編集し、「生徒に公開する」で公開できる（`PUT /materials/{id}/content`、`POST /materials/{id}/publish`・`unpublish`、先生のみ）。
- 生徒は `GET /shared` で公開中の教材を見て、`POST /shared/{id}/add` で自分用にコピーして学ぶ。成績・復習予定は生徒ごと。コピー後に先生が編集しても、コピー済みの分は変わらない。
- コピーした教材は作り直し不可（先生の内容を上書きしない）。1人の教材数の上限（20件）には数える。

## 教材の削除とメールログイン
- `DELETE /materials/{id}`：自分の教材を削除（Cloud Storage のファイル本体も消す）。先生が削除・公開をやめても、生徒がコピーした分は生徒の手元に残る。
- ログインは Google に加えて、メールアドレス＋パスワード（新規登録・パスワード再設定メール）。Firebase コンソールの Authentication で「メール/パスワード」を有効にしておくこと。
