import { useEffect, useState } from "react";
import { api, type Material, type ReviewItem, type Role, type Shared } from "../api";
import { fmtDate, pct } from "../format";
import Study from "./Study";

export default function Materials({ role, onUsageChange }: { role: Role; onUsageChange: () => void }) {
  const [list, setList] = useState<Material[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState("");

  const [title, setTitle] = useState("");
  const [text, setText] = useState("");
  const [due, setDue] = useState("");
  const [importance, setImportance] = useState(3);
  const [files, setFiles] = useState<File[]>([]);
  const [busy, setBusy] = useState(false);

  const [today, setToday] = useState<ReviewItem[]>([]);
  const [shared, setShared] = useState<Shared[]>([]);

  const load = () => {
    api.review().then((r) => setToday(r.filter((i) => i.due))).catch(() => setToday([]));
    onUsageChange(); // 教材数・生成回数の表示を更新
    if (role === "student") api.shared().then(setShared).catch(() => setShared([]));
    return api.listMaterials().then(setList).catch((e) => setError(e.message));
  };
  useEffect(() => {
    load();
  }, []);

  async function addSample() {
    setBusy(true);
    setError("");
    try {
      const m = await api.createSample();
      await load();
      setSelected(m.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function remove(m: { id: string; title: string; published?: boolean }) {
    const note = m.published ? "\n公開中です。生徒がすでにコピーした分は、生徒の手元に残ります。" : "";
    if (!window.confirm(`「${m.title}」を削除します。元に戻せません。${note}\nよろしいですか？`)) return;
    setBusy(true);
    setError("");
    try {
      await api.remove(m.id);
      setSelected(null);
      await load();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function openShared(s: Shared) {
    setBusy(true);
    setError("");
    try {
      const m = await api.addShared(s.id); // 追加済みなら、自分用のコピーがそのまま返る
      await load();
      setSelected(m.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const payload = {
        title,
        text,
        due_date: due ? new Date(due).toISOString() : null,
        importance,
      };
      // ファイルがあれば multipart、なければ従来のテキスト登録
      const m = files.length > 0 ? await api.uploadMaterial({ ...payload, files }) : await api.createMaterial(payload);
      setTitle("");
      setText("");
      setDue("");
      setFiles([]);
      await load();
      setSelected(m.id);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  if (selected) {
    const m = list.find((x) => x.id === selected);
    return (
      <div>
        <button className="btn-link mb-3" onClick={() => { setSelected(null); load(); }}>
          ← 教材一覧へ
        </button>
        {m ? <Study material={m} role={role} onChanged={load} onDelete={() => remove(m)} /> : <p>教材が見つかりません</p>}
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {error && <p className="error-box">エラー: {error}</p>}

      <section>
        <h2 className="text-lg font-bold mb-2">今日の復習</h2>
        {list.length === 0 ? (
          <p className="text-slate-500">教材を登録すると、ここに今日取り組むものが表示されます。</p>
        ) : today.length === 0 ? (
          <p className="bg-green-50 text-green-800 border border-green-200 rounded-xl p-3">今日取り組む教材はありません。お疲れさまでした。</p>
        ) : (
          <ul className="space-y-2">
            {today.slice(0, 3).map((it) => (
              <li key={it.material_id} className="card !p-3 sm:!p-4 flex items-center justify-between gap-3">
                <div>
                  <span className="font-bold break-words">{it.title}</span>
                  <span className="block text-xs text-slate-500">
                    {it.reason} ／ 優先度 {it.score}
                  </span>
                </div>
                <button className="btn-primary btn-sm shrink-0" onClick={() => setSelected(it.material_id)}>
                  学習する
                </button>
              </li>
            ))}
          </ul>
        )}
        {today.length > 3 && <p className="text-xs text-slate-500 mt-1">ほか {today.length - 3} 件は「重点復習」タブで確認できます。</p>}
      </section>

      {role === "student" && shared.length > 0 && (
        <section>
          <h2 className="text-lg font-bold mb-2">先生から届いた教材</h2>
          <ul className="space-y-2">
            {shared.map((s) => (
              <li key={s.id} className="card !p-3 sm:!p-4 flex items-center justify-between gap-3">
                <div>
                  <span className="font-bold break-words">{s.title}</span>
                  <span className="block text-xs text-slate-500">
                    {s.teacher_name} 先生 ／ 期限 {fmtDate(s.due_date)}
                  </span>
                </div>
                <button className="btn-primary btn-sm shrink-0" disabled={busy} onClick={() => openShared(s)}>
                  {s.added ? "学習する" : "追加して学ぶ"}
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <div className="flex items-center justify-between mb-2">
          <h2 className="text-lg font-bold">教材を登録</h2>
          <button type="button" disabled={busy} onClick={addSample} className="btn-link">
            サンプル教材を追加
          </button>
        </div>
        <form onSubmit={submit} className="card space-y-3">
          <input
            className="field"
            placeholder="タイトル（例: 二次関数の最大値・最小値）"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            required
          />
          <textarea
            className="field h-40"
            placeholder="授業のノートや配布資料の本文を貼り付けてください（PDF・画像を選ぶ場合は空でも可）"
            value={text}
            onChange={(e) => setText(e.target.value)}
            required={files.length === 0}
          />
          <label className="block text-sm">
            PDF・画像（任意。PNG / JPEG / WebP、1つ10MBまで、最大5つ）
            <input
              type="file"
              multiple
              accept="application/pdf,image/png,image/jpeg,image/webp"
              className="block mt-1 text-sm file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3 file:py-1.5 file:text-indigo-700"
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
          </label>
          <div className="flex flex-wrap gap-4 items-center">
            <label className="text-sm">
              テスト等の期限（任意）
              <input type="date" className="ml-2 border border-slate-300 rounded-lg px-2 py-1" value={due} onChange={(e) => setDue(e.target.value)} />
            </label>
            <label className="text-sm">
              重要度
              <select className="ml-2 border border-slate-300 rounded-lg px-2 py-1" value={importance} onChange={(e) => setImportance(Number(e.target.value))}>
                {[1, 2, 3, 4, 5].map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </select>
            </label>
          </div>
          <button disabled={busy} className="btn-primary w-full sm:w-auto">
            {busy ? "登録中…" : "登録する"}
          </button>
        </form>
      </section>

      <section>
        <h2 className="text-lg font-bold mb-2">教材一覧</h2>
        {list.length === 0 ? (
          <p className="text-slate-500">まだ教材がありません。</p>
        ) : (
          <ul className="space-y-2">
            {list.map((m) => (
              <li key={m.id} className="flex items-stretch gap-2">
                <button onClick={() => setSelected(m.id)} className="flex-1 min-w-0 text-left card !p-3 sm:!p-4 hover:border-indigo-300 hover:bg-indigo-50/40 transition">
                  <span className="font-bold">{m.title}</span>
                  <span className="block text-xs text-slate-500">
                    {m.shared_from ? "先生から ／ " : ""}{m.generated ? "生成済み" : "未生成"}{m.published ? " ／ 公開中" : ""} ／ 理解度 {pct(m.mastery)} ／ 次回復習 {fmtDate(m.next_review_at)}
                  </span>
                </button>
                <button
                  disabled={busy}
                  onClick={() => remove(m)}
                  aria-label={`${m.title} を削除`}
                  className="shrink-0 px-3 text-sm text-red-600 border border-slate-200 rounded-2xl bg-white hover:bg-red-50 disabled:opacity-50"
                >
                  削除
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
