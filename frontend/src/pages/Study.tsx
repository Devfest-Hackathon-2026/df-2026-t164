import { useEffect, useState } from "react";
import { api, type AnswerResult, type Material, type Quiz, type Role, type Summary } from "../api";
import { fmtDate, pct } from "../format";
import Editor from "./Editor";

export default function Study({
  material,
  role,
  onChanged,
  onDelete,
}: {
  material: Material;
  role: Role;
  onChanged: () => void;
  onDelete: () => void;
}) {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [quiz, setQuiz] = useState<Quiz | null>(null);
  const [answers, setAnswers] = useState<number[]>([]);
  const [kind, setKind] = useState<"pre" | "post">("pre");
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [editing, setEditing] = useState(false);

  async function togglePublish() {
    setBusy(true);
    setError("");
    try {
      await (material.published ? api.unpublish(material.id) : api.publish(material.id));
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function loadGenerated(regenerate = false) {
    setBusy(true);
    setError("");
    try {
      const s = await api.generate(material.id, regenerate);
      const q = await api.quiz(material.id);
      setSummary(s);
      setQuiz(q);
      setAnswers(Array(q.questions.length).fill(-1));
      setResult(null);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  // 生成済みの教材は開いた時点で表示する（再解析しない）
  useEffect(() => {
    if (material.generated) loadGenerated(false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [material.id]);

  async function submit() {
    setBusy(true);
    setError("");
    try {
      // 未回答（-1）は不正解として送られる
      const r = await api.submit(material.id, kind, answers);
      setResult(r);
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-5">
      <div>
        <h2 className="text-xl font-bold">{material.title}</h2>
        <p className="text-xs text-slate-500">
          期限 {fmtDate(material.due_date)} ／ 重要度 {material.importance} ／ 理解度 {pct(material.mastery)}
        </p>
        {material.shared_from && <p className="text-xs text-indigo-700">{material.shared_from} 先生から届いた教材</p>}
        {material.file_names.length > 0 && (
          <p className="text-xs text-slate-500">添付: {material.file_names.join("、")}</p>
        )}
      </div>

      {error && <p className="error-box">エラー: {error}</p>}

      <div className="text-right">
        <button className="text-sm text-red-600 hover:underline" disabled={busy} onClick={onDelete}>
          この教材を削除
        </button>
      </div>

      {!quiz && (
        <button disabled={busy} onClick={() => loadGenerated(false)} className="btn-primary w-full sm:w-auto">
          {busy ? "AIが生成中…（数十秒かかることがあります）" : "AIで要点とクイズを生成する"}
        </button>
      )}

      {role === "teacher" && material.generated && !editing && (
        <section className="card flex flex-wrap items-center justify-between gap-3">
          <p className="text-sm">
            {material.published ? (
              <span className="text-green-700 font-medium">公開中（生徒に表示されています）</span>
            ) : (
              <span className="text-slate-600">未公開（生徒には見えません）</span>
            )}
          </p>
          <div className="flex gap-3 items-center">
            <button className="btn-link" disabled={busy} onClick={() => setEditing(true)}>
              要点とクイズを確認・編集
            </button>
            <button className="btn-primary btn-sm" disabled={busy} onClick={togglePublish}>
              {material.published ? "公開をやめる" : "生徒に公開する"}
            </button>
          </div>
        </section>
      )}

      {editing && (
        <Editor
          materialId={material.id}
          onCancel={() => setEditing(false)}
          onSaved={() => {
            setEditing(false);
            loadGenerated(false);
          }}
        />
      )}

      {!editing && summary && (
        <section className="card">
          <h3 className="font-bold mb-2">{summary.source === "teacher" ? "先生が確認した要点" : "AIがまとめた要点"}</h3>
          <ul className="list-disc pl-5 space-y-1">
            {summary.summary.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ul>
          <p className="text-xs text-slate-400 mt-2">
            生成元: {summary.source === "vertex" ? "Gemini（Vertex AI）" : summary.source === "teacher" ? "先生が確認・編集" : summary.source}
            {summary.source.startsWith("dummy") && "（AIを使わない代用の生成です）"}
          </p>
          {!material.shared_from && (
            <button disabled={busy} onClick={() => loadGenerated(true)} className="btn-link !text-xs mt-1">
              作り直す
            </button>
          )}
        </section>
      )}

      {!editing && quiz && (
        <section className="card space-y-4">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
            <h3 className="font-bold">確認クイズ</h3>
            <label className="text-sm">
              <input type="radio" checked={kind === "pre"} onChange={() => setKind("pre")} /> 事前（学ぶ前）
            </label>
            <label className="text-sm">
              <input type="radio" checked={kind === "post"} onChange={() => setKind("post")} /> 事後（学んだ後）
            </label>
          </div>
          {quiz.questions.map((q, qi) => (
            <fieldset key={qi} className="space-y-1.5">
              <legend className="font-medium mb-1">
                Q{qi + 1}. {q.question}
              </legend>
              {q.choices.map((c, ci) => {
                const graded = result !== null;
                const isCorrect = graded && result!.correct_indexes[qi] === ci;
                const isWrongPick = graded && answers[qi] === ci && !result!.results[qi];
                return (
                  <label
                    key={ci}
                    className={`block rounded-xl px-3 py-2 border cursor-pointer hover:bg-slate-50 ${
                      isCorrect ? "border-green-500 bg-green-50" : isWrongPick ? "border-red-400 bg-red-50" : "border-slate-200"
                    }`}
                  >
                    <input
                      type="radio"
                      name={`q${qi}`}
                      disabled={graded}
                      checked={answers[qi] === ci}
                      onChange={() => setAnswers((a) => a.map((v, i) => (i === qi ? ci : v)))}
                    />{" "}
                    {c}
                  </label>
                );
              })}
              {result && <p className="text-sm text-slate-600">{result.results[qi] ? "⭕ 正解。" : "❌ 不正解。"} {result.explanations[qi]}</p>}
            </fieldset>
          ))}

          {!result ? (
            <button disabled={busy || answers.every((a) => a < 0)} onClick={submit} className="btn-primary w-full sm:w-auto">
              {busy ? "採点中…" : "採点する"}
            </button>
          ) : (
            <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-3">
              <p className="font-bold">
                正答率 {pct(result.accuracy)}（{result.kind === "pre" ? "事前テスト" : "事後テスト"}）
              </p>
              <p className="text-sm">
                {result.next_review_at
                  ? `次の復習は ${fmtDate(result.next_review_at)} です。`
                  : "事前テストは現状把握のみです。学んだあと、事後テストで復習予定が決まります。"}
              </p>
              <button
                className="btn-link mt-2"
                onClick={() => {
                  setResult(null);
                  setAnswers(Array(quiz.questions.length).fill(-1));
                  setKind("post");
                }}
              >
                もう一度解く（事後テスト）
              </button>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
