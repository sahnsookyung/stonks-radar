import { syncCsrfTokenFromCookie } from "./api";

export const TICKER_WORKSPACE_STORAGE_KEY = "stonks-radar:ticker-workspace:v1";
const TICKER_ALERT_DRAFT_STORAGE_KEY = "stonks-radar:ticker-alert-drafts:v1";

export type TickerNote = {
  content: string;
  updated_at: string | null;
  conflicts: Array<{ content: string; updated_at: string | null; source: "merge" }>;
};

export type TickerComparison = {
  id: string;
  symbols: string[];
  updated_at: string | null;
};

export type TickerWorkspace = {
  version: 1;
  watchlist: string[];
  notes: Record<string, TickerNote>;
  comparisons: TickerComparison[];
};

export type TickerWorkspacePayload = {
  revision: number;
  workspace: TickerWorkspace;
  updated_at: string | null;
};

export type MemberSession = {
  id: string;
  email: string;
  role: "owner" | "admin" | "editor" | "viewer" | "member";
};

export type AlertDraft = {
  symbol: string;
  rule_type: string;
  configuration: Record<string, string | number | boolean>;
  cooldown_seconds: number;
  email_enabled: boolean;
};

export function emptyTickerWorkspace(): TickerWorkspace {
  return { version: 1, watchlist: [], notes: {}, comparisons: [] };
}

export function normalizeTickerSymbol(value: string) {
  return value.trim().toUpperCase().replace(/[^A-Z0-9.\-]/g, "").slice(0, 16);
}

export function loadTickerWorkspace(): TickerWorkspace {
  try {
    const raw = globalThis.localStorage?.getItem(TICKER_WORKSPACE_STORAGE_KEY);
    return raw ? normalizeTickerWorkspace(JSON.parse(raw)) : emptyTickerWorkspace();
  } catch {
    return emptyTickerWorkspace();
  }
}

export function saveTickerWorkspace(workspace: TickerWorkspace) {
  const normalized = normalizeTickerWorkspace(workspace);
  try {
    globalThis.localStorage?.setItem(TICKER_WORKSPACE_STORAGE_KEY, JSON.stringify(normalized));
  } catch {
    // Storage can be disabled or full. The current React state remains usable.
  }
  return normalized;
}

export function normalizeTickerWorkspace(value: unknown): TickerWorkspace {
  if (!value || typeof value !== "object") return emptyTickerWorkspace();
  const input = value as Partial<TickerWorkspace>;
  const watchlist = Array.isArray(input.watchlist)
    ? Array.from(new Set(input.watchlist.map((symbol) => normalizeTickerSymbol(String(symbol))).filter(Boolean))).slice(0, 100)
    : [];
  const notes = normalizeNotes(input.notes);
  const comparisons = Array.isArray(input.comparisons)
    ? input.comparisons
        .filter((comparison): comparison is TickerComparison => Boolean(comparison && typeof comparison === "object"))
        .map((comparison) => ({
          id: String(comparison.id || "").replace(/[^A-Za-z0-9._:-]/g, "").slice(0, 80),
          symbols: Array.from(
            new Set((Array.isArray(comparison.symbols) ? comparison.symbols : []).map((symbol) => normalizeTickerSymbol(String(symbol))).filter(Boolean))
          ).slice(0, 4),
          updated_at: typeof comparison.updated_at === "string" ? comparison.updated_at : null
        }))
        .filter((comparison) => comparison.id && comparison.symbols.length)
        .slice(0, 50)
    : [];
  return { version: 1, watchlist, notes, comparisons };
}

export function updateTickerNote(workspace: TickerWorkspace, symbol: string, content: string): TickerWorkspace {
  const normalizedSymbol = normalizeTickerSymbol(symbol);
  const previous = workspace.notes[normalizedSymbol];
  return saveTickerWorkspace({
    ...workspace,
    notes: {
      ...workspace.notes,
      [normalizedSymbol]: {
        content: content.slice(0, 20_000),
        updated_at: new Date().toISOString(),
        conflicts: previous?.conflicts ?? []
      }
    }
  });
}

export function toggleWatchedTicker(workspace: TickerWorkspace, symbol: string): TickerWorkspace {
  const normalizedSymbol = normalizeTickerSymbol(symbol);
  const watched = workspace.watchlist.includes(normalizedSymbol);
  return saveTickerWorkspace({
    ...workspace,
    watchlist: watched
      ? workspace.watchlist.filter((item) => item !== normalizedSymbol)
      : [...workspace.watchlist, normalizedSymbol].slice(0, 100)
  });
}

export function saveComparison(workspace: TickerWorkspace, symbols: string[]): TickerWorkspace {
  const normalized = Array.from(new Set(symbols.map(normalizeTickerSymbol).filter(Boolean))).slice(0, 4);
  if (!normalized.length) return workspace;
  const id = normalized.join(":");
  const comparison = { id, symbols: normalized, updated_at: new Date().toISOString() };
  return saveTickerWorkspace({
    ...workspace,
    comparisons: [comparison, ...workspace.comparisons.filter((item) => item.id !== id)].slice(0, 50)
  });
}

export async function getMemberSession(signal?: AbortSignal): Promise<MemberSession | null> {
  try {
    const response = await fetch("/api/auth/me", { credentials: "include", headers: { Accept: "application/json" }, signal });
    if (response.status === 401 || response.status === 403) return null;
    if (!response.ok) return null;
    const payload = (await response.json()) as Partial<MemberSession>;
    if (!payload.id || !payload.email || !payload.role) return null;
    return payload as MemberSession;
  } catch {
    return null;
  }
}

export async function getServerTickerWorkspace(signal?: AbortSignal): Promise<TickerWorkspacePayload | null> {
  const response = await fetch("/api/member/ticker-workspace", {
    credentials: "include",
    headers: { Accept: "application/json" },
    signal
  });
  if ([401, 403, 404].includes(response.status)) return null;
  if (!response.ok) throw new Error(`Ticker workspace failed: ${response.status}`);
  return normalizePayload(await response.json());
}

export async function mergeServerTickerWorkspace(
  workspace: TickerWorkspace,
  revision: number,
  signal?: AbortSignal
): Promise<TickerWorkspacePayload | null> {
  return writeWorkspace("/api/member/ticker-workspace/merge", workspace, revision, signal);
}

export async function saveServerTickerWorkspace(
  workspace: TickerWorkspace,
  revision: number,
  signal?: AbortSignal
): Promise<TickerWorkspacePayload | null> {
  return writeWorkspace("/api/member/ticker-workspace", workspace, revision, signal, "PUT");
}

export function loadAlertDraft(symbol: string): AlertDraft | null {
  try {
    const drafts = JSON.parse(globalThis.localStorage?.getItem(TICKER_ALERT_DRAFT_STORAGE_KEY) || "{}") as Record<string, AlertDraft>;
    return drafts[normalizeTickerSymbol(symbol)] ?? null;
  } catch {
    return null;
  }
}

export function saveAlertDraft(draft: AlertDraft) {
  try {
    const drafts = JSON.parse(globalThis.localStorage?.getItem(TICKER_ALERT_DRAFT_STORAGE_KEY) || "{}") as Record<string, AlertDraft>;
    drafts[normalizeTickerSymbol(draft.symbol)] = draft;
    globalThis.localStorage?.setItem(TICKER_ALERT_DRAFT_STORAGE_KEY, JSON.stringify(drafts));
  } catch {
    // Keep the editor usable when storage is unavailable.
  }
}

function normalizeNotes(value: unknown): Record<string, TickerNote> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return Object.entries(value as Record<string, unknown>)
    .slice(0, 500)
    .reduce<Record<string, TickerNote>>((result, [rawSymbol, rawNote]) => {
      const symbol = normalizeTickerSymbol(rawSymbol);
      if (!symbol) return result;
      const note = rawNote && typeof rawNote === "object" ? (rawNote as Partial<TickerNote>) : { content: String(rawNote ?? "") };
      result[symbol] = {
        content: String(note.content ?? "").slice(0, 20_000),
        updated_at: typeof note.updated_at === "string" ? note.updated_at : null,
        conflicts: Array.isArray(note.conflicts)
          ? note.conflicts.slice(0, 20).map((conflict) => ({
              content: String(conflict?.content ?? "").slice(0, 20_000),
              updated_at: typeof conflict?.updated_at === "string" ? conflict.updated_at : null,
              source: "merge" as const
            }))
          : []
      };
      return result;
    }, {});
}

async function writeWorkspace(
  path: string,
  workspace: TickerWorkspace,
  revision: number,
  signal?: AbortSignal,
  method = "POST"
): Promise<TickerWorkspacePayload | null> {
  const csrf = syncCsrfTokenFromCookie();
  if (!csrf) return null;
  const response = await fetch(path, {
    method,
    credentials: "include",
    headers: { Accept: "application/json", "Content-Type": "application/json", "x-csrf-token": csrf },
    body: JSON.stringify({ workspace: normalizeTickerWorkspace(workspace), revision }),
    signal
  });
  if ([401, 403, 404].includes(response.status)) return null;
  const payload = await response.json().catch(() => ({}));
  if (response.status === 409 && payload.current) return normalizePayload(payload.current);
  if (!response.ok) throw new Error(`Ticker workspace write failed: ${response.status}`);
  return normalizePayload(payload);
}

function normalizePayload(value: unknown): TickerWorkspacePayload {
  const payload = (value || {}) as Partial<TickerWorkspacePayload>;
  return {
    revision: Number.isInteger(payload.revision) ? Number(payload.revision) : 0,
    workspace: normalizeTickerWorkspace(payload.workspace),
    updated_at: typeof payload.updated_at === "string" ? payload.updated_at : null
  };
}
