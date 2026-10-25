"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useHealth } from "@/lib/hooks";
import { API_URL } from "@/lib/api";

const NAV = [
  { href: "/", label: "Research Lab", icon: "M12 3v5l-5 9a2 2 0 0 0 1.7 3h6.6A2 2 0 0 0 17 17l-5-9V3M9 3h6" },
  { href: "/experiments", label: "Experiments", icon: "M4 6h16M4 12h16M4 18h10" },
  { href: "/datasets", label: "Datasets", icon: "M4 6c0-1.7 3.6-3 8-3s8 1.3 8 3-3.6 3-8 3-8-1.3-8-3Zm0 0v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" },
  { href: "/history", label: "Research History", icon: "M6 3v12M18 9v12M6 15a3 3 0 1 0 0 6 3 3 0 0 0 0-6Zm12-12a3 3 0 1 0 0 6 3 3 0 0 0 0-6ZM6 9c0 4 12 2 12 6" },
  { href: "/settings", label: "Settings", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7.6 7.6 0 0 0-2-1.2L14.5 3h-5l-.4 2.6a7.6 7.6 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-1a7.6 7.6 0 0 0 2 1.2l.4 2.6h5l.4-2.6a7.6 7.6 0 0 0 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z" },
];

export function Icon({ d, className = "h-4 w-4" }: { d: string; className?: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.7} strokeLinecap="round"
      strokeLinejoin="round" className={className} aria-hidden="true">
      <path d={d} />
    </svg>
  );
}

function ThemeToggle() {
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);
  useEffect(() => {
    let saved: string | null = null;
    try { saved = localStorage.getItem("eos-theme"); } catch { /* storage unavailable */ }
    const initial = saved === "light" || saved === "dark" ? saved
      : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
    setTheme(initial);
    document.documentElement.dataset.theme = initial;
  }, []);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("eos-theme", next); } catch { /* ignore */ }
  };
  return (
    <button onClick={toggle} className="rounded-lg border border-line px-2.5 py-1.5 text-xs text-ink-2 hover:bg-surface-2"
      aria-label="Toggle colour theme">
      {theme === "dark" ? "☀ Light" : "☾ Dark"}
    </button>
  );
}

function HealthBanner() {
  const { health, error } = useHealth();
  if (error) {
    return (
      <div role="alert" className="border-b border-line bg-bad-soft px-4 py-2 text-sm text-bad">
        Backend unreachable at <code>{API_URL}</code>. Start it with <code>uvicorn app.main:app</code> (see README).
      </div>
    );
  }
  if (health && health.llm_mode !== "nemotron") {
    return (
      <div role="status" className="border-b border-line bg-warn-soft px-4 py-2 text-sm text-warn">
        <strong>OFFLINE MODE — Nemotron not used.</strong> Reasoning runs on deterministic templates; measurements are
        still real. Set <code>NEBIUS_API_KEY</code> and <code>NEBIUS_MODEL</code> to enable NVIDIA Nemotron via Nebius
        Token Factory.
      </div>
    );
  }
  return null;
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const active = (href: string) => (href === "/" ? path === "/" : path.startsWith(href));
  return (
    <div className="min-h-screen md:flex">
      <aside className="border-b border-line bg-surface md:sticky md:top-0 md:h-screen md:w-60 md:shrink-0 md:border-b-0 md:border-r">
        <div className="flex items-center justify-between px-4 py-4 md:block">
          <Link href="/" className="flex items-center gap-2">
            <span className="grid h-8 w-8 place-items-center rounded-lg bg-accent text-sm font-bold text-surface">E</span>
            <span>
              <span className="block text-[15px] font-semibold leading-tight">ExperimentOS</span>
              <span className="hidden text-[11px] text-muted md:block">Autonomous experimentation</span>
            </span>
          </Link>
          <div className="md:hidden"><ThemeToggle /></div>
        </div>
        <nav className="flex gap-1 overflow-x-auto px-2 pb-2 md:flex-col md:overflow-visible md:pb-0" aria-label="Main">
          {NAV.map((n) => (
            <Link key={n.href} href={n.href}
              className={`flex shrink-0 items-center gap-2.5 rounded-lg px-3 py-2 text-sm transition-colors ${
                active(n.href) ? "bg-accent-soft font-medium text-accent" : "text-ink-2 hover:bg-surface-2"}`}>
              <Icon d={n.icon} />
              {n.label}
            </Link>
          ))}
        </nav>
        <div className="absolute bottom-4 left-4 hidden md:block"><ThemeToggle /></div>
        <p className="absolute bottom-5 right-4 hidden text-[10px] text-muted md:block">Nebius × NVIDIA</p>
      </aside>
      <div className="min-w-0 flex-1">
        <HealthBanner />
        <main className="mx-auto max-w-6xl px-4 py-6 md:px-8 md:py-8">{children}</main>
      </div>
    </div>
  );
}
