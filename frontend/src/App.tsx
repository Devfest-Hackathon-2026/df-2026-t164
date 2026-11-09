import { useCallback, useEffect, useState } from "react";
import type { User } from "firebase/auth";
import { api, type Me } from "./api";
import { logout, watchAuth } from "./firebase";
import Login from "./pages/Login";
import Materials from "./pages/Materials";
import Review from "./pages/Review";
import RoleSelect from "./pages/RoleSelect";

type Tab = "materials" | "review";

export default function App() {
  const [tab, setTab] = useState<Tab>("materials");
  // 学習画面から復習リストへ移るとき、一覧を再取得させるためのキー
  const [reviewKey, setReviewKey] = useState(0);

  // undefined = 確認中 / null = 未ログイン
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [me, setMe] = useState<Me | null>(null);
  const [meError, setMeError] = useState("");

  useEffect(() => watchAuth(setUser), []);

  const refreshMe = useCallback(() => {
    api
      .me()
      .then((m) => {
        setMe(m);
        setMeError("");
      })
      .catch((e) => setMeError(e.message));
  }, []);

  useEffect(() => {
    if (user) refreshMe();
    else setMe(null);
  }, [user, refreshMe]);

  const tabClass = (t: Tab) =>
    `flex-1 sm:flex-none px-5 py-2 rounded-full text-sm font-medium transition ${
      tab === t ? "bg-white text-indigo-700 shadow" : "text-indigo-100 hover:bg-white/15"
    }`;

  const ready = Boolean(user && me && me.role);

  return (
    <div className="min-h-screen bg-slate-50 text-slate-800">
      <header className="bg-gradient-to-r from-indigo-600 to-violet-600 px-4 pt-4 pb-3 shadow">
        <div className="max-w-3xl mx-auto">
          <div className="flex items-start justify-between gap-3">
            <div>
              <h1 className="text-white text-xl font-bold tracking-wide">SchoolRestart</h1>
              <p className="text-indigo-100 text-xs mb-3">休んだ授業から、無理なく学び直す</p>
            </div>
            {user && (
              <div className="text-right text-xs text-indigo-100 shrink-0">
                <span className="block">
                  {me?.name || user.displayName || user.email}
                  {me?.role && `（${me.role === "teacher" ? "先生" : "生徒"}）`}
                </span>
                <button className="underline hover:text-white" onClick={() => logout()}>
                  ログアウト
                </button>
              </div>
            )}
          </div>
          {ready && (
            <nav className="flex gap-1 bg-black/10 rounded-full p-1 sm:w-fit">
              <button className={tabClass("materials")} onClick={() => setTab("materials")}>
                教材・学習
              </button>
              <button
                className={tabClass("review")}
                onClick={() => {
                  setReviewKey((k) => k + 1);
                  setTab("review");
                }}
              >
                重点復習
              </button>
            </nav>
          )}
        </div>
      </header>
      <main className="max-w-3xl mx-auto p-4 pb-12">
        {user === undefined ? (
          <p className="text-slate-500">読み込み中…</p>
        ) : user === null ? (
          <Login />
        ) : meError ? (
          <div className="space-y-2">
            <p className="error-box">サーバーに接続できませんでした: {meError}</p>
            <button className="btn-link" onClick={refreshMe}>
              もう一度試す
            </button>
          </div>
        ) : !me ? (
          <p className="text-slate-500">読み込み中…</p>
        ) : !me.role ? (
          <RoleSelect onDone={setMe} />
        ) : (
          <>
            <p className="text-xs text-slate-500 mb-3">
              教材 {me.materials_used}/{me.materials_limit} 件 ／ 今日のAI生成 {me.generations_today}/{me.generations_limit} 回
            </p>
            {tab === "materials" ? <Materials role={me.role} onUsageChange={refreshMe} /> : <Review key={reviewKey} />}
          </>
        )}
      </main>
    </div>
  );
}
