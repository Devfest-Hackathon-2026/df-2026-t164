import { useEffect, useState } from "react";
import { api, type ReviewItem } from "../api";
import { fmtDate, pct } from "../format";

const LABELS: Record<string, string> = {
  weakness: "理解不足",
  deadline: "期限",
  review_need: "復習の必要性",
  importance: "重要度",
};

export default function Review() {
  const [items, setItems] = useState<ReviewItem[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.review().then(setItems).catch((e) => setError(e.message));
  }, []);

  if (error) return <p className="error-box">読み込みに失敗しました: {error}</p>;
  if (!items) return <p className="text-slate-500">読み込み中…</p>;
  if (items.length === 0) return <p className="card text-slate-500">教材がありません。「教材・学習」から登録してください。</p>;

  return (
    <div>
      <h2 className="text-lg font-bold mb-1">重点復習（優先度の高い順）</h2>
      <p className="text-sm text-slate-500 mb-4">
        スコアはサーバー側で、理解不足・期限・復習の必要性・重要度から計算しています。
      </p>
      <ol className="space-y-3">
        {items.map((it, i) => (
          <li key={it.material_id} className="card">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <span className="font-bold break-words">
                  {i + 1}. {it.title}
                </span>
                <p className="text-sm text-indigo-700 mt-0.5">{it.reason}</p>
              </div>
              <div className="text-right shrink-0">
                <span className="text-3xl font-bold text-indigo-600 leading-none">{it.score}</span>
                <span className="block text-[10px] text-slate-400">優先度</span>
              </div>
            </div>
            <p className="text-xs text-slate-500 mt-2">
              理解度: {pct(it.mastery)} ／ 次回復習: {fmtDate(it.next_review_at)}
            </p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3">
              {Object.entries(it.breakdown).map(([k, v]) => (
                <div key={k}>
                  <div className="flex justify-between text-xs text-slate-500">
                    <span>{LABELS[k] ?? k}</span>
                    <span>{Math.round(v * 100)}%</span>
                  </div>
                  <div className="h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div className="h-full bg-indigo-400 rounded-full" style={{ width: `${Math.round(v * 100)}%` }} />
                  </div>
                </div>
              ))}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
