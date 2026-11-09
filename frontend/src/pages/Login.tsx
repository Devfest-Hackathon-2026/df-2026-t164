import { useState } from "react";
import { loginWithEmail, loginWithGoogle, registerWithEmail, resetPassword } from "../firebase";

type Mode = "login" | "register";

const MESSAGES: Record<string, string> = {
  "auth/invalid-credential": "メールアドレスかパスワードが違います",
  "auth/invalid-email": "メールアドレスの形式が正しくありません",
  "auth/email-already-in-use": "このメールアドレスはすでに登録されています。ログインしてください",
  "auth/weak-password": "パスワードは6文字以上にしてください",
  "auth/too-many-requests": "試行回数が多すぎます。しばらくしてからお試しください",
  "auth/user-disabled": "このアカウントは使えません",
  "auth/network-request-failed": "通信に失敗しました。接続を確認してください",
  "auth/operation-not-allowed": "この方法のログインは、まだ有効になっていません",
  "auth/popup-blocked": "ポップアップがブロックされました。許可してもう一度お試しください",
};

export default function Login() {
  const [mode, setMode] = useState<Mode>("login");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [info, setInfo] = useState("");
  const [busy, setBusy] = useState(false);

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError("");
    setInfo("");
    try {
      await action();
    } catch (e) {
      const code = (e as { code?: string }).code ?? "";
      // 自分で閉じた場合はエラーにしない
      if (code === "auth/popup-closed-by-user" || code === "auth/cancelled-popup-request") return;
      setError(MESSAGES[code] ?? `失敗しました: ${(e as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    run(() => (mode === "login" ? loginWithEmail(email.trim(), password) : registerWithEmail(name.trim(), email.trim(), password)));
  };

  const reset = () => {
    if (!email.trim()) {
      setError("パスワードを再設定するメールアドレスを入力してください");
      return;
    }
    run(async () => {
      await resetPassword(email.trim());
      setInfo("再設定のメールを送りました。届かない場合は、迷惑メールのフォルダも確認してください");
    });
  };

  return (
    <div className="card space-y-4 mt-6">
      <div className="text-center space-y-1">
        <h2 className="text-lg font-bold">はじめましょう</h2>
        <p className="text-sm text-slate-600">休んだ授業の教材を、AIが要点とクイズにまとめます。</p>
      </div>

      {error && <p className="error-box">{error}</p>}
      {info && <p className="bg-green-50 text-green-800 border border-green-200 rounded-xl px-3 py-2 text-sm">{info}</p>}

      <button onClick={() => run(loginWithGoogle)} disabled={busy} className="btn-primary w-full">
        Google でログイン
      </button>

      <p className="text-center text-xs text-slate-400">または</p>

      <div className="flex gap-1 bg-slate-100 rounded-full p-1">
        {(["login", "register"] as Mode[]).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => {
              setMode(m);
              setError("");
              setInfo("");
            }}
            className={`flex-1 py-1.5 rounded-full text-sm font-medium transition ${mode === m ? "bg-white shadow text-indigo-700" : "text-slate-500"}`}
          >
            {m === "login" ? "メールでログイン" : "メールで新規登録"}
          </button>
        ))}
      </div>

      <form onSubmit={submit} className="space-y-3">
        {mode === "register" && (
          <input className="field" placeholder="お名前（表示に使います）" value={name} onChange={(e) => setName(e.target.value)} required maxLength={50} autoComplete="name" />
        )}
        <input className="field" type="email" placeholder="メールアドレス" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="email" />
        <input
          className="field"
          type="password"
          placeholder={mode === "register" ? "パスワード（6文字以上）" : "パスワード"}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          minLength={mode === "register" ? 6 : undefined}
          autoComplete={mode === "register" ? "new-password" : "current-password"}
        />
        <button disabled={busy} className="btn-primary w-full">
          {busy ? "処理中…" : mode === "login" ? "ログイン" : "登録してはじめる"}
        </button>
        {mode === "login" && (
          <button type="button" className="btn-link block mx-auto" disabled={busy} onClick={reset}>
            パスワードを忘れた場合
          </button>
        )}
      </form>
    </div>
  );
}
