import type { ExperimentStatus, HypothesisStatus } from "@/types";
import { hypothesisLabel, isActive, statusLabel } from "@/lib/format";

const tone = {
  good: "bg-good-soft text-good",
  warn: "bg-warn-soft text-warn",
  bad: "bg-bad-soft text-bad",
  info: "bg-info-soft text-info",
  neutral: "bg-surface-2 text-ink-2",
} as const;

export function StatusBadge({ status }: { status: ExperimentStatus }) {
  const t = status === "COMPLETED" ? "good" : status === "FAILED" ? "bad" : status === "CANCELLED" ? "neutral"
    : isActive(status) ? "info" : "neutral";
  const icon = status === "COMPLETED" ? "✓" : status === "FAILED" ? "✕" : status === "CANCELLED" ? "–" : "●";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${tone[t]}`}>
      <span aria-hidden="true" className={isActive(status) ? "pulse" : ""}>{icon}</span>
      {statusLabel(status)}
    </span>
  );
}

const H_TONE: Record<HypothesisStatus, keyof typeof tone> = {
  SUPPORTED: "good", PARTIALLY_SUPPORTED: "warn", REJECTED: "bad", INCONCLUSIVE: "neutral",
};
const H_ICON: Record<HypothesisStatus, string> = {
  SUPPORTED: "✓", PARTIALLY_SUPPORTED: "◐", REJECTED: "✕", INCONCLUSIVE: "?",
};

export function HypothesisBadge({ status, large = false }: { status: HypothesisStatus | null; large?: boolean }) {
  if (!status) return <span className="text-muted">—</span>;
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full font-semibold tracking-wide ${tone[H_TONE[status]]} ${
      large ? "px-4 py-1.5 text-sm" : "px-2.5 py-0.5 text-xs"}`}>
      <span aria-hidden="true">{H_ICON[status]}</span>
      {hypothesisLabel(status)}
    </span>
  );
}

export function Chip({ children, mono = false }: { children: React.ReactNode; mono?: boolean }) {
  return (
    <span className={`inline-flex items-center rounded-md border border-line bg-surface-2 px-1.5 py-0.5 text-[11px] text-ink-2 ${mono ? "font-mono" : ""}`}>
      {children}
    </span>
  );
}
