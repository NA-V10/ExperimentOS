import type { ExperimentStatus, HypothesisStatus, Params } from "@/types";

export const pct = (x: number | null | undefined, digits = 1) =>
  x == null ? "—" : `${(x * 100).toFixed(digits)}%`;

export const signed = (x: number | null | undefined, unit = "", digits = 1) =>
  x == null ? "—" : `${x > 0 ? "+" : ""}${x.toFixed(digits)}${unit}`;

export const expNumber = (n: number) => `#${String(n).padStart(3, "0")}`;

export const time = (iso: string) =>
  new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });

export const date = (iso: string) =>
  new Date(iso).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

export function paramsLabel(p: Params): string {
  const entries = Object.entries(p);
  if (!entries.length) return "defaults";
  return entries.map(([k, v]) => `${k}=${v === null ? "none" : v}`).join(", ");
}

export const ACTIVE: ExperimentStatus[] = ["CREATED", "PLANNING", "VALIDATING", "GENERATING_CODE", "QUEUED", "RUNNING", "ANALYZING"];
export const isActive = (s: ExperimentStatus) => ACTIVE.includes(s);

export const statusLabel = (s: ExperimentStatus) =>
  s === "GENERATING_CODE" ? "Generating code" : s.charAt(0) + s.slice(1).toLowerCase();

export const hypothesisLabel = (s: HypothesisStatus | null | undefined) =>
  s ? s.replace("_", " ") : "—";
