import { useEffect, useState } from "react";
import { api, type Content } from "../api";

// 先生用：AI が作った要点とクイズを確認して、直す画面。
export default function Editor({ materialId, onSaved, onCancel }: { materialId: string; onSaved: () => void; onCancel: () => void }) {
  const [c, setC] = useState<Content | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.content(materialId).then(setC).catch((e) => setError(e.message));
  }, [materialId]);

  if (!c) return error ? <p className="error-box">エラー: {error}</p> : <p className="text-slate-500">読み込み中…</p>;

  const setSummary = (i: number, v: string) => setC({ ...c, summary: c.summary.map((s, k) => (k === i ? v : s)) });
  const setQ = (qi: number, patch: Partial<Content["questions"][number]>) =>
    setC({ ...c, questions: c.questions.map((q, k) => (k === qi ? { ...q, ...patch } : q)) });
  const setChoice = (qi: number, ci: number, v: string) =>
    setQ(qi, { choices: c.questions[qi].choices.map((x, k) => (k === ci ? v : x)) });

  function removeChoice(qi: number, ci: number) {
    const q = c!.questions[qi];
    // 正解より前を消したら、正解の番号を1つ前にずらす。正解自体は消せない
    if (ci === q.answer_index) return;
    setQ(qi, { choices: q.choices.filter((_, k) => k !== ci), answer_index: ci < q.answer_index ? q.answer_index - 1 : q.answer_index });
  }

  async function save() {
    setBusy(true);
    setError("");
    try {
      await api.saveContent(materialId, { summary: c!.summary, questions: c!.questions });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <p className="text-sm text-slate-600">AIが作った内容を確認して、必要なら直してください。保存すると、この教材の内容が置き換わります。</p>
      {error && <p className="error-box">エラー: {error}</p>}

      <section className="card space-y-2">
        <h3 className="font-bold">要点</h3>
        {c.summary.map((s, i) => (
          <div key={i} className="flex gap-2 items-start">
            <textarea className="field h-20" value={s} onChange={(e) => setSummary(i, e.target.value)} />
            <button
              type="button"
              className="btn-link shrink-0"
              disabled={c.summary.length <= 1}
              onClick={() => setC({ ...c, summary: c.summary.filter((_, k) => k !== i) })}
            >
              削除
            </button>
          </div>
        ))}
        <button type="button" className="btn-link" onClick={() => setC({ ...c, summary: [...c.summary, ""] })}>
          ＋ 要点を追加
        </button>
      </section>

      {c.questions.map((q, qi) => (
        <section key={qi} className="card space-y-2">
          <div className="flex items-center justify-between">
            <h3 className="font-bold">問題 {qi + 1}</h3>
            <button
              type="button"
              className="btn-link"
              disabled={c.questions.length <= 1}
              onClick={() => setC({ ...c, questions: c.questions.filter((_, k) => k !== qi) })}
            >
              この問題を削除
            </button>
          </div>
          <textarea className="field h-20" value={q.question} onChange={(e) => setQ(qi, { question: e.target.value })} placeholder="問題文" />
          <p className="text-xs text-slate-500">選択肢（正解の左のボタンを選びます）</p>
          {q.choices.map((ch, ci) => (
            <div key={ci} className="flex items-center gap-2">
              <input type="radio" name={`ans${qi}`} checked={q.answer_index === ci} onChange={() => setQ(qi, { answer_index: ci })} aria-label="正解にする" />
              <input className="field" value={ch} onChange={(e) => setChoice(qi, ci, e.target.value)} />
              <button type="button" className="btn-link shrink-0" disabled={q.choices.length <= 2 || q.answer_index === ci} onClick={() => removeChoice(qi, ci)}>
                削除
              </button>
            </div>
          ))}
          {q.choices.length < 6 && (
            <button type="button" className="btn-link" onClick={() => setQ(qi, { choices: [...q.choices, ""] })}>
              ＋ 選択肢を追加
            </button>
          )}
          <textarea className="field h-16" value={q.explanation} onChange={(e) => setQ(qi, { explanation: e.target.value })} placeholder="解説（任意）" />
        </section>
      ))}
      <button
        type="button"
        className="btn-link"
        disabled={c.questions.length >= 20}
        onClick={() => setC({ ...c, questions: [...c.questions, { question: "", choices: ["", ""], answer_index: 0, explanation: "" }] })}
      >
        ＋ 問題を追加
      </button>

      <div className="flex gap-3">
        <button className="btn-primary" disabled={busy} onClick={save}>
          {busy ? "保存中…" : "保存する"}
        </button>
        <button className="btn-link" disabled={busy} onClick={onCancel}>
          キャンセル
        </button>
      </div>
    </div>
  );
}
