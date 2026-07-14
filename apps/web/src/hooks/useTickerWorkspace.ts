import { useCallback, useEffect, useRef, useState } from "react";
import {
  getMemberSession,
  getServerTickerWorkspace,
  loadTickerWorkspace,
  mergeServerTickerWorkspace,
  saveServerTickerWorkspace,
  saveTickerWorkspace,
  type MemberSession,
  type TickerWorkspace
} from "../lib/tickerWorkspace";

export type TickerWorkspaceSyncStatus = "local" | "syncing" | "synced" | "conflict" | "unavailable";

export function useTickerWorkspace() {
  const [workspace, setWorkspaceState] = useState<TickerWorkspace>(() => loadTickerWorkspace());
  const [session, setSession] = useState<MemberSession | null | undefined>(undefined);
  const [serverAvailable, setServerAvailable] = useState(false);
  const [syncStatus, setSyncStatus] = useState<TickerWorkspaceSyncStatus>("local");
  const initialized = useRef(false);
  const saveSequence = useRef(0);
  const revision = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    void (async () => {
      const member = await getMemberSession(controller.signal);
      if (controller.signal.aborted) return;
      setSession(member);
      if (!member) {
        initialized.current = true;
        return;
      }
      setSyncStatus("syncing");
      try {
        const server = await getServerTickerWorkspace(controller.signal);
        if (!server) {
          setSyncStatus("unavailable");
          initialized.current = true;
          return;
        }
        const local = loadTickerWorkspace();
        const merged = await mergeServerTickerWorkspace(local, server.revision, controller.signal);
        const resolved = merged ?? server;
        saveTickerWorkspace(resolved.workspace);
        setWorkspaceState(resolved.workspace);
        revision.current = resolved.revision;
        setServerAvailable(Boolean(merged));
        setSyncStatus(merged ? "synced" : "unavailable");
      } catch (error) {
        if (!(error instanceof DOMException && error.name === "AbortError")) setSyncStatus("unavailable");
      } finally {
        initialized.current = true;
      }
    })();
    return () => controller.abort();
  }, []);

  const setWorkspace = useCallback((next: TickerWorkspace | ((current: TickerWorkspace) => TickerWorkspace)) => {
    setWorkspaceState((current) => saveTickerWorkspace(typeof next === "function" ? next(current) : next));
  }, []);

  useEffect(() => {
    if (!initialized.current || !session || !serverAvailable) return undefined;
    const sequence = ++saveSequence.current;
    const controller = new AbortController();
    const timer = globalThis.window.setTimeout(() => {
      setSyncStatus("syncing");
      void (async () => {
        try {
          const saved = await saveServerTickerWorkspace(workspace, revision.current, controller.signal);
          if (!saved || sequence !== saveSequence.current) return;
          if (saved.revision !== revision.current + 1) {
            setSyncStatus("conflict");
            const merged = await mergeServerTickerWorkspace(workspace, saved.revision, controller.signal);
            if (!merged || sequence !== saveSequence.current) return;
            saveTickerWorkspace(merged.workspace);
            setWorkspaceState(merged.workspace);
            revision.current = merged.revision;
          } else {
            revision.current = saved.revision;
          }
          setSyncStatus("synced");
        } catch (error) {
          if (!(error instanceof DOMException && error.name === "AbortError")) setSyncStatus("unavailable");
        }
      })();
    }, 650);
    return () => {
      globalThis.window.clearTimeout(timer);
      controller.abort();
    };
  }, [serverAvailable, session, workspace]);

  return {
    workspace,
    setWorkspace,
    session,
    syncStatus,
    isSignedIn: Boolean(session),
    serverAvailable
  };
}
