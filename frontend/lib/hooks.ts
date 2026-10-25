"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, subscribeEvents } from "./api";
import { isActive } from "./format";
import type { AgentEvent, ExperimentDetail, Health } from "@/types";

export function useHealth() {
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api.health().then(setHealth).catch((e: Error) => setError(e.message));
  }, []);
  return { health, error };
}

/** Experiment detail + live SSE events. Detail is refetched on real state changes. */
export function useExperiment(id: string) {
  const [exp, setExp] = useState<ExperimentDetail | null>(null);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const refetchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const load = useCallback(async (withEvents = true) => {
    try {
      const d = await api.getExperiment(id, withEvents);
      setExp(d);
      if (d.events) {
        const evs = d.events;
        setEvents((prev) => (evs.length >= prev.length ? evs : prev));
      }
      return d;
    } catch (e) {
      setError((e as Error).message);
      return null;
    }
  }, [id]);

  const scheduleRefetch = useCallback(() => {
    if (refetchTimer.current) return;
    refetchTimer.current = setTimeout(() => {
      refetchTimer.current = null;
      void load(false); // state only — events already arrive over SSE
    }, 250);
  }, [load]);

  useEffect(() => {
    let unsub: (() => void) | null = null;
    let cancelled = false;
    load().then((d) => {
      if (!d || cancelled || !isActive(d.status)) return;
      const lastId = d.events?.at(-1)?.id ?? 0;
      unsub = subscribeEvents(
        id,
        lastId,
        (ev) => {
          setEvents((prev) => (prev.some((p) => p.id === ev.id) ? prev : [...prev, ev]));
          if (ev.event_type === "status" || ev.event_type === "stage" || ev.event_type === "tool_result") {
            scheduleRefetch();
          }
        },
        () => void load(),
      );
    });
    return () => {
      cancelled = true;
      unsub?.();
      if (refetchTimer.current) clearTimeout(refetchTimer.current);
    };
  }, [id, load, scheduleRefetch]);

  return { exp, events, error, reload: load };
}
