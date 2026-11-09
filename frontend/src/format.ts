export function fmtDate(iso: string | null): string {
  if (!iso) return "未設定";
  return new Date(iso).toLocaleDateString("ja-JP", { year: "numeric", month: "numeric", day: "numeric" });
}

export function pct(x: number | null): string {
  return x === null ? "未測定" : `${Math.round(x * 100)}%`;
}
