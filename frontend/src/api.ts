// バックエンド API の型と呼び出し。形は backend/schemas.py に合わせる。
// 本番ビルドはバックエンドと同じオリジンから配信されるので相対パス。開発時は別ポートのバックエンドへ。
import { getToken } from "./firebase";

const BASE = import.meta.env.VITE_API_BASE ?? (import.meta.env.PROD ? "" : "http://localhost:8000");

export type Material = {
  id: string;
  title: string;
  due_date: string | null;
  importance: number;
  created_at: string;
  file_names: string[];
  generated: boolean;
  mastery: number | null;
  review_step: number | null;
  next_review_at: string | null;
  published: boolean;
  shared_from: string | null;
};

export type Content = {
  summary: string[];
  questions: { question: string; choices: string[]; answer_index: number; explanation: string }[];
  source: string;
};
export type Shared = {
  id: string;
  title: string;
  teacher_name: string;
  due_date: string | null;
  importance: number;
  added: boolean;
  my_material_id: string | null;
};

export type Role = "teacher" | "student";
export type Me = {
  uid: string;
  email: string;
  name: string;
  role: Role | null;
  materials_used: number;
  materials_limit: number;
  generations_today: number;
  generations_limit: number;
};

export type Summary = { material_id: string; summary: string[]; source: string };
export type Quiz = { material_id: string; questions: { question: string; choices: string[] }[] };
export type AnswerResult = {
  kind: string;
  results: boolean[];
  correct_indexes: number[];
  explanations: string[];
  accuracy: number;
  mastery: number;
  review_step: number | null;
  next_review_at: string | null;
};
export type ReviewItem = {
  material_id: string;
  title: string;
  score: number;
  breakdown: Record<string, number>;
  reason: string;
  due: boolean;
  next_review_at: string | null;
  mastery: number | null;
};

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData のときは Content-Type をブラウザに任せる（boundary が付くため）
  const headers: Record<string, string> = init?.body instanceof FormData ? {} : { "Content-Type": "application/json" };
  const token = await getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(BASE + path, { ...init, headers });
  if (!res.ok) {
    let detail = `${res.status}`;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* 本文なし */
    }
    throw new Error(detail);
  }
  if (res.status === 204) return null as T;
  return res.json() as Promise<T>;
}

export const api = {
  me: () => call<Me>("/me"),
  setRole: (role: Role) => call<Me>("/me/role", { method: "POST", body: JSON.stringify({ role }) }),
  listMaterials: () => call<Material[]>("/materials"),
  createMaterial: (b: { title: string; text: string; due_date: string | null; importance: number }) =>
    call<Material>("/materials", { method: "POST", body: JSON.stringify(b) }),
  createSample: () => call<Material>("/materials/sample", { method: "POST" }),
  uploadMaterial: (b: { title: string; text: string; due_date: string | null; importance: number; files: File[] }) => {
    const fd = new FormData();
    fd.append("title", b.title);
    fd.append("text", b.text);
    fd.append("importance", String(b.importance));
    if (b.due_date) fd.append("due_date", b.due_date);
    b.files.forEach((f) => fd.append("files", f));
    return call<Material>("/materials/upload", { method: "POST", body: fd });
  },
  generate: (id: string, regenerate = false) =>
    call<Summary>(`/materials/${id}/generate?regenerate=${regenerate}`, { method: "POST" }),
  quiz: (id: string) => call<Quiz>(`/materials/${id}/quiz`),
  submit: (id: string, kind: "pre" | "post", answers: number[]) =>
    call<AnswerResult>(`/materials/${id}/answers`, { method: "POST", body: JSON.stringify({ kind, answers }) }),
  review: () => call<ReviewItem[]>("/review"),
  // 先生用
  content: (id: string) => call<Content>(`/materials/${id}/content`),
  saveContent: (id: string, b: Pick<Content, "summary" | "questions">) =>
    call<Material>(`/materials/${id}/content`, { method: "PUT", body: JSON.stringify(b) }),
  remove: (id: string) => call<null>(`/materials/${id}`, { method: "DELETE" }),
  publish: (id: string) => call<Material>(`/materials/${id}/publish`, { method: "POST" }),
  unpublish: (id: string) => call<Material>(`/materials/${id}/unpublish`, { method: "POST" }),
  // 生徒用：先生が公開した教材
  shared: () => call<Shared[]>("/shared"),
  addShared: (id: string) => call<Material>(`/shared/${id}/add`, { method: "POST" }),
};
