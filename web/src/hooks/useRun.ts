import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { AuditEvent, Candidate, EvidenceItem, Hypothesis, Investigation } from "../types";

interface RunState {
  investigation: Investigation | null;
  audit: AuditEvent[];
  connected: boolean;
  error: string | null;
  /** Candidate ids whose status changed in the last event, for the flash effect. */
  flashed: Set<string>;
}

const EMPTY: RunState = {
  investigation: null,
  audit: [],
  connected: false,
  error: null,
  flashed: new Set(),
};

function upsert<T extends { id: string }>(list: T[], item: T): T[] {
  const index = list.findIndex((existing) => existing.id === item.id);
  if (index === -1) return [...list, item];
  const next = list.slice();
  next[index] = item;
  return next;
}

export function useRun(runId: string | null) {
  const [state, setState] = useState<RunState>(EMPTY);
  const source = useRef<EventSource | null>(null);
  const flashTimer = useRef<number | null>(null);

  const refresh = useCallback(async () => {
    if (!runId) return;
    try {
      const [investigation, audit] = await Promise.all([api.get(runId), api.audit(runId)]);
      setState((prev) => ({ ...prev, investigation, audit, error: null }));
    } catch (err) {
      setState((prev) => ({ ...prev, error: (err as Error).message }));
    }
  }, [runId]);

  const flash = useCallback((id: string) => {
    setState((prev) => {
      const next = new Set(prev.flashed);
      next.add(id);
      return { ...prev, flashed: next };
    });
    if (flashTimer.current) window.clearTimeout(flashTimer.current);
    flashTimer.current = window.setTimeout(() => {
      setState((prev) => ({ ...prev, flashed: new Set() }));
    }, 1200);
  }, []);

  useEffect(() => {
    if (!runId) {
      setState(EMPTY);
      return;
    }
    setState({ ...EMPTY, flashed: new Set() });
    void refresh();

    const es = new EventSource(api.eventsUrl(runId));
    source.current = es;

    es.onopen = () => setState((prev) => ({ ...prev, connected: true }));
    es.onerror = () => setState((prev) => ({ ...prev, connected: false }));

    es.onmessage = (message) => {
      let payload: Record<string, unknown>;
      try {
        payload = JSON.parse(message.data);
      } catch {
        return;
      }

      setState((prev) => {
        const inv = prev.investigation;
        switch (payload.type) {
          case "snapshot":
            return {
              ...prev,
              investigation: payload.investigation as Investigation,
              connected: true,
            };
          case "investigation": {
            if (!inv) return prev;
            return {
              ...prev,
              investigation: {
                ...inv,
                status: payload.status as string,
                status_detail: payload.status_detail as string,
                progress: payload.progress as number,
              },
            };
          }
          case "evidence": {
            if (!inv) return prev;
            return {
              ...prev,
              investigation: {
                ...inv,
                evidence: upsert(inv.evidence, payload.item as EvidenceItem),
              },
            };
          }
          case "hypothesis": {
            if (!inv) return prev;
            return {
              ...prev,
              investigation: {
                ...inv,
                hypotheses: upsert(inv.hypotheses, payload.item as Hypothesis),
              },
            };
          }
          case "candidate": {
            if (!inv) return prev;
            const incoming = payload.candidate as Candidate;
            const before = inv.candidates.find((c) => c.id === incoming.id);
            if (before && before.status !== incoming.status) {
              queueMicrotask(() => flash(incoming.id));
            }
            return {
              ...prev,
              investigation: { ...inv, candidates: upsert(inv.candidates, incoming) },
            };
          }
          case "audit": {
            const event = payload.event as AuditEvent;
            const audit = upsert(prev.audit, event).sort((a, b) => a.seq - b.seq);
            // Terminal and package states change artifacts/benchling, which the
            // stream does not carry — pull the full object once.
            if (event.next_state === "PACKAGE_CREATED" || event.next_state === "COMPLETED") {
              queueMicrotask(() => void refresh());
            }
            return { ...prev, audit };
          }
          default:
            return prev;
        }
      });
    };

    return () => {
      es.close();
      source.current = null;
      if (flashTimer.current) window.clearTimeout(flashTimer.current);
    };
  }, [runId, refresh, flash]);

  return { ...state, refresh };
}
