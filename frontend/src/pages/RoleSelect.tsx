import { useState } from "react";
import { api, type Me, type Role } from "../api";

const OPTIONS: { role: Role; title: string; desc: string }[] = [
  { role: "student", title: "生徒", desc: "休んだ授業の教材を登録して、要点とクイズで学び直します。" },
  { role: "teacher", title: "先生", desc: "教材やクイズを確認・編集して、生徒に届けます。" },
];

export default function RoleSelect({ onDone }: { onDone: (me: Me) => void }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function choose(role: Role) {
    // あとから変更できないので、確認してから決める
    const label = role === "teacher" ? "先生" : "生徒";
    if (!window.confirm(`「${label}」で登録します。あとから変更はできません。よろしいですか？`)) return;
    setBusy(true);
    setError("");
    try {
      onDone(await api.setRole(role));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-4 mt-2">
      <div>
        <h2 className="text-lg font-bold">あなたは、どちらですか？</h2>
        <p className="text-sm text-slate-500">最初に1度だけ選びます。あとから変更はできません。</p>
      </div>
      {error && <p className="error-box">{error}</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {OPTIONS.map((o) => (
          <button
            key={o.role}
            disabled={busy}
            onClick={() => choose(o.role)}
            className="card text-left hover:border-indigo-300 hover:bg-indigo-50/40 transition disabled:opacity-50"
          >
            <span className="block font-bold text-lg">{o.title}</span>
            <span className="block text-sm text-slate-600 mt-1">{o.desc}</span>
          </button>
        ))}
      </div>
    </div>
  );
}
