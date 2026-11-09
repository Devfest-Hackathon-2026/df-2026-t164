"""ログインの確認。Firebase Authentication が発行した ID トークンをサーバーで検証する。

AUTH_BACKEND=firebase のとき本番の検証。未設定（none）のときはローカル・テスト用の固定ユーザー。
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Identity:
    uid: str
    email: str
    name: str


class AuthError(Exception):
    pass


def backend() -> str:
    return os.environ.get("AUTH_BACKEND", "none").lower()


def verify_token(token: str) -> Identity:
    """Firebase の ID トークンを検証して本人を返す。不正・期限切れは AuthError。"""
    from google.auth.transport import requests as g_requests
    from google.oauth2 import id_token

    project = os.environ.get("FIREBASE_PROJECT_ID") or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise AuthError("FIREBASE_PROJECT_ID が設定されていません")
    try:
        claims = id_token.verify_firebase_token(token, g_requests.Request(), audience=project)
    except Exception as e:  # 署名・期限・宛先の不一致など
        raise AuthError(str(e)) from e
    uid = claims.get("user_id") or claims.get("sub")
    if not uid:
        raise AuthError("uid がありません")
    return Identity(uid=uid, email=claims.get("email", ""), name=claims.get("name", ""))


DEV_IDENTITY = Identity(uid="dev-user", email="dev@example.com", name="開発ユーザー")
