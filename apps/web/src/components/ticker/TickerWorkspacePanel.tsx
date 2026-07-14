import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, FileText, LogIn, Save, ShieldAlert } from "lucide-react";
import {
  createTickerAlertRule,
  listTickerAlertEvents,
  listTickerAlertRules,
  memberSignInUrl,
  updateNotificationPreferences
} from "../../lib/tickerApi";
import {
  loadAlertDraft,
  saveAlertDraft,
  updateTickerNote,
  type AlertDraft,
  type TickerWorkspace
} from "../../lib/tickerWorkspace";
import type { TrackedTicker } from "../../lib/trackedTickers";
import type { TickerWorkspaceSyncStatus } from "../../hooks/useTickerWorkspace";

const ruleTypes = [
  "price_threshold",
  "rsi",
  "macd_cross",
  "volume_spike",
  "sec_filing",
  "news_spike",
  "short_interest_update",
  "option_iv_threshold"
] as const;

export function TickerWorkspacePanel({
  ticker,
  locale,
  workspace,
  setWorkspace,
  isSignedIn,
  syncStatus,
  focusTarget,
  focusRequest
}: Readonly<{
  ticker: TrackedTicker;
  locale: "en" | "ko";
  workspace: TickerWorkspace;
  setWorkspace: (workspace: TickerWorkspace | ((current: TickerWorkspace) => TickerWorkspace)) => void;
  isSignedIn: boolean;
  syncStatus: TickerWorkspaceSyncStatus;
  focusTarget?: "note" | "alert" | null;
  focusRequest?: number;
}>) {
  const isKo = locale === "ko";
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const alertRef = useRef<HTMLSelectElement>(null);
  const queryClient = useQueryClient();
  const existing = workspace.notes[ticker.symbol];
  const [noteStatus, setNoteStatus] = useState<"saved" | "editing">("saved");
  const [draft, setDraft] = useState<AlertDraft>(() => loadAlertDraft(ticker.symbol) ?? defaultDraft(ticker.symbol));
  const [draftMessage, setDraftMessage] = useState("");
  const rulesQuery = useQuery({ queryKey: ["ticker-alert-rules"], queryFn: ({ signal }) => listTickerAlertRules(signal), enabled: isSignedIn, retry: false });
  const eventsQuery = useQuery({ queryKey: ["ticker-alert-events"], queryFn: ({ signal }) => listTickerAlertEvents(signal), enabled: isSignedIn, retry: false });
  const createMutation = useMutation({
    mutationFn: async () => {
      if (draft.email_enabled) await updateNotificationPreferences(locale, true);
      return createTickerAlertRule(draft);
    },
    onSuccess: async () => {
      setDraftMessage(isKo ? "서버 알림 규칙을 저장했습니다." : "Background alert rule saved.");
      await queryClient.invalidateQueries({ queryKey: ["ticker-alert-rules"] });
    }
  });

  useEffect(() => {
    if (focusTarget === "note") noteRef.current?.focus();
    if (focusTarget === "alert") alertRef.current?.focus();
  }, [focusRequest, focusTarget]);

  useEffect(() => {
    const next = loadAlertDraft(ticker.symbol) ?? defaultDraft(ticker.symbol);
    setDraft(next);
    setDraftMessage("");
  }, [ticker.symbol]);

  function updateDraft(patch: Partial<AlertDraft>) {
    const next = { ...draft, ...patch, symbol: ticker.symbol };
    setDraft(next);
    saveAlertDraft(next);
    setDraftMessage(isKo ? "초안을 이 브라우저에 저장했습니다." : "Draft saved in this browser.");
  }

  function handleNote(value: string) {
    setNoteStatus("editing");
    setWorkspace((current) => updateTickerNote(current, ticker.symbol, value));
    globalThis.window.setTimeout(() => setNoteStatus("saved"), 700);
  }

  function saveRule() {
    saveAlertDraft(draft);
    if (isSignedIn) createMutation.mutate();
    else setDraftMessage(isKo ? "로컬 초안을 저장했습니다. 백그라운드 평가와 이메일에는 로그인이 필요합니다." : "Local draft saved. Sign in for background evaluation and email.");
  }

  const tickerRules = (rulesQuery.data?.rules ?? []).filter((rule) => rule.symbol === ticker.symbol);
  const tickerEvents = (eventsQuery.data?.events ?? []).filter((event) => event.symbol === ticker.symbol || !event.symbol);

  return (
    <section className="grid gap-5 lg:grid-cols-2" aria-label={isKo ? "티커 노트와 알림" : "Ticker notes and alerts"}>
      <div className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <SectionTitle id="ticker-note-heading" icon={<FileText className="h-5 w-5" />} title={isKo ? "리서치 노트" : "Research Note"} subtitle={isKo ? "익명 상태에서는 로컬, 로그인 후에는 리비전 충돌 보호와 함께 서버에 동기화됩니다." : "Stored locally when anonymous and synchronized with revision conflict protection after sign-in."} />
          <span className="badge border-line bg-panelAlt text-muted">{noteStatus === "editing" ? (isKo ? "저장 중" : "Saving") : syncLabel(syncStatus, locale)}</span>
        </div>
        <label htmlFor="ticker-research-note" className="sr-only">{isKo ? `${ticker.symbol} 리서치 노트` : `${ticker.symbol} research note`}</label>
        <textarea
          ref={noteRef}
          id="ticker-research-note"
          className="input-control mt-4 min-h-[220px] w-full resize-y leading-6"
          value={existing?.content ?? ""}
          maxLength={20_000}
          onChange={(event) => handleNote(event.target.value)}
          placeholder={isKo ? "근거, 반대 논지, 확인할 공시를 기록하세요." : "Record evidence, counterpoints, and filings to verify."}
        />
        <div className="mt-2 flex flex-wrap justify-between gap-2 text-xs text-muted">
          <span>{(existing?.content.length ?? 0).toLocaleString()}/20,000</span>
          <span>{existing?.updated_at ? `${isKo ? "수정" : "Updated"} ${formatTime(existing.updated_at, locale)}` : (isKo ? "아직 저장된 내용 없음" : "No saved content yet")}</span>
        </div>
        {existing?.conflicts.length ? (
          <details className="mt-4 rounded-md border border-warning/40 bg-warning/10 p-3 text-sm">
            <summary className="focus-ring cursor-pointer rounded font-semibold text-warning">{isKo ? `병합 충돌 사본 ${existing.conflicts.length}개` : `${existing.conflicts.length} preserved merge conflict copies`}</summary>
            <div className="mt-3 grid gap-2">{existing.conflicts.map((conflict, index) => <pre key={`${conflict.updated_at}-${index}`} className="whitespace-pre-wrap rounded bg-paper p-3 text-xs leading-5 text-muted">{conflict.content}</pre>)}</div>
          </details>
        ) : null}
      </div>

      <div className="panel p-5">
        <SectionTitle id="ticker-alert-heading" icon={<Bell className="h-5 w-5" />} title={isKo ? "알림 규칙" : "Alert Rule"} subtitle={isKo ? "인앱 알림은 항상 켜지고 이메일은 규칙별 옵트인입니다." : "In-app delivery is always enabled; email is opt-in per rule."} />
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <label htmlFor="ticker-alert-type" className="grid gap-1 text-xs font-semibold uppercase text-muted">
            {isKo ? "규칙 유형" : "Rule type"}
            <select ref={alertRef} id="ticker-alert-type" className="input-control min-h-11" value={draft.rule_type} onChange={(event) => updateDraft({ rule_type: event.target.value, configuration: defaultConfiguration(event.target.value) })}>
              {ruleTypes.map((type) => <option key={type} value={type}>{ruleLabel(type, locale)}</option>)}
            </select>
          </label>
          <RuleConfiguration draft={draft} locale={locale} onChange={(configuration) => updateDraft({ configuration })} />
          <label htmlFor="ticker-alert-cooldown" className="grid gap-1 text-xs font-semibold uppercase text-muted">
            {isKo ? "재알림 대기(분)" : "Cooldown (minutes)"}
            <input id="ticker-alert-cooldown" type="number" min={0} max={43_200} className="input-control min-h-11" value={Math.round(draft.cooldown_seconds / 60)} onChange={(event) => updateDraft({ cooldown_seconds: Math.max(0, Number(event.target.value) * 60) })} />
          </label>
          <label className="flex min-h-11 items-center gap-3 rounded-md border border-line bg-panelAlt px-3 text-sm font-semibold">
            <input type="checkbox" checked={draft.email_enabled} onChange={(event) => updateDraft({ email_enabled: event.target.checked })} />
            {isKo ? "이메일도 받기" : "Also send email"}
          </label>
        </div>
        <button type="button" className="primary-action mt-4" onClick={saveRule} disabled={createMutation.isPending}><Save className="h-4 w-4" />{createMutation.isPending ? (isKo ? "저장 중" : "Saving") : (isKo ? "규칙 저장" : "Save rule")}</button>
        {draftMessage ? <p role="status" className="mt-3 text-sm text-muted">{draftMessage}</p> : null}
        {createMutation.error ? <p role="alert" className="mt-3 text-sm text-danger">{createMutation.error.message}</p> : null}
        {!isSignedIn ? (
          <a href={memberSignInUrl(globalThis.window.location.pathname + globalThis.window.location.search)} className="secondary-action mt-3"><LogIn className="h-4 w-4" />{isKo ? "백그라운드 알림을 위해 로그인" : "Sign in for background alerts"}</a>
        ) : null}
        {draft.rule_type === "option_iv_threshold" ? <p className="signal-warning mt-3 p-3 text-xs leading-5">{isKo ? "옵션 IV 평가는 검증된 개인 공급자 연결이 추가로 필요합니다." : "Option-IV evaluation also requires a verified private provider connection."}</p> : null}

        {isSignedIn ? (
          <div className="mt-5 grid gap-4 border-t border-line pt-4">
            <div><h3 className="text-sm font-semibold">{isKo ? "저장된 규칙" : "Saved rules"}</h3><div className="mt-2 grid gap-2">{tickerRules.length ? tickerRules.map((rule) => <div key={rule.id} className="rounded-md border border-line bg-panelAlt p-3 text-xs"><span className="font-semibold">{ruleLabel(rule.rule_type, locale)}</span> · {rule.active ? (isKo ? "활성" : "active") : (isKo ? "중지" : "paused")}</div>) : <p className="text-sm text-muted">{isKo ? "저장된 규칙이 없습니다." : "No saved rules."}</p>}</div></div>
            <div><h3 className="text-sm font-semibold">{isKo ? "최근 인앱 이벤트" : "Recent in-app events"}</h3><div className="mt-2 grid gap-2">{tickerEvents.length ? tickerEvents.slice(0, 5).map((event) => <div key={event.id} className="rounded-md border border-line bg-panelAlt p-3 text-xs"><span className="font-semibold">{event.reason}</span><div className="mt-1 text-muted">{formatTime(event.source_time || event.created_at, locale)}</div></div>) : <p className="text-sm text-muted">{isKo ? "발생한 이벤트가 없습니다." : "No events triggered yet."}</p>}</div></div>
          </div>
        ) : null}
        <div className="mt-4 flex items-start gap-2 text-xs leading-5 text-muted"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-warning" /><span>{isKo ? "알림과 이메일은 투자 조언이 아니며 원문 시각과 규칙 이유를 포함합니다." : "Alerts and emails are not financial advice and include source time and rule reason."}</span></div>
      </div>
    </section>
  );
}

function RuleConfiguration({ draft, locale, onChange }: Readonly<{ draft: AlertDraft; locale: "en" | "ko"; onChange: (configuration: Record<string, string | number | boolean>) => void }>) {
  const eventOnly = ["sec_filing", "news_spike", "short_interest_update"].includes(draft.rule_type);
  if (eventOnly) return <div className="rounded-md border border-line bg-panelAlt p-3 text-xs leading-5 text-muted">{locale === "ko" ? "새 수집 이벤트가 발생하면 평가합니다." : "Evaluated when a new ingestion event arrives."}</div>;
  if (draft.rule_type === "macd_cross") return <label htmlFor="ticker-alert-direction" className="grid gap-1 text-xs font-semibold uppercase text-muted">{locale === "ko" ? "방향" : "Direction"}<select id="ticker-alert-direction" className="input-control min-h-11" value={String(draft.configuration.direction ?? "bullish")} onChange={(event) => onChange({ direction: event.target.value })}><option value="bullish">Bullish</option><option value="bearish">Bearish</option></select></label>;
  const hasOperator = draft.rule_type !== "volume_spike";
  return <div className="grid min-w-0 grid-cols-[minmax(0,1fr)_minmax(90px,0.7fr)] gap-2">
    {hasOperator ? <label htmlFor="ticker-alert-operator" className="grid min-w-0 gap-1 text-xs font-semibold uppercase text-muted">{locale === "ko" ? "조건" : "Condition"}<select id="ticker-alert-operator" className="input-control min-h-11 min-w-0 w-full" value={String(draft.configuration.operator ?? "above")} onChange={(event) => onChange({ ...draft.configuration, operator: event.target.value })}><option value="above">{locale === "ko" ? "초과" : "Above"}</option><option value="below">{locale === "ko" ? "미만" : "Below"}</option></select></label> : <div className="grid min-w-0 place-items-center rounded-md border border-line bg-panelAlt px-2 text-xs text-muted">{locale === "ko" ? "평균 대비 배수" : "Times average"}</div>}
    <label htmlFor="ticker-alert-value" className="grid min-w-0 gap-1 text-xs font-semibold uppercase text-muted">{locale === "ko" ? "값" : "Value"}<input id="ticker-alert-value" type="number" step="any" className="input-control min-h-11 min-w-0 w-full" value={Number(draft.configuration.value ?? 0)} onChange={(event) => onChange({ ...draft.configuration, value: Number(event.target.value) })} /></label>
  </div>;
}

function defaultDraft(symbol: string): AlertDraft { return { symbol, rule_type: "price_threshold", configuration: { operator: "above", value: 0 }, cooldown_seconds: 3600, email_enabled: false }; }
function defaultConfiguration(type: string): Record<string, string | number | boolean> { if (type === "macd_cross") return { direction: "bullish" }; if (["sec_filing", "news_spike", "short_interest_update"].includes(type)) return {}; if (type === "volume_spike") return { value: 2 }; return { operator: "above", value: 0 }; }
function ruleLabel(type: string, locale: "en" | "ko") { const labels: Record<string, [string, string]> = { price_threshold: ["Price threshold", "가격 임계값"], rsi: ["RSI threshold", "RSI 임계값"], macd_cross: ["MACD cross", "MACD 교차"], volume_spike: ["Volume spike", "거래량 급증"], sec_filing: ["SEC filing", "SEC 공시"], news_spike: ["News spike", "뉴스 급증"], short_interest_update: ["Short-interest update", "공매도 업데이트"], option_iv_threshold: ["Option IV threshold", "옵션 IV 임계값"] }; return labels[type]?.[locale === "ko" ? 1 : 0] ?? type; }
function syncLabel(status: TickerWorkspaceSyncStatus, locale: "en" | "ko") { const labels: Record<TickerWorkspaceSyncStatus, [string, string]> = { local: ["Saved locally", "로컬 저장"], syncing: ["Syncing", "동기화 중"], synced: ["Synced", "동기화됨"], conflict: ["Resolving conflict", "충돌 병합 중"], unavailable: ["Offline mirror", "오프라인 미러"] }; return labels[status][locale === "ko" ? 1 : 0]; }
function formatTime(value: string, locale: "en" | "ko") { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString(locale === "ko" ? "ko-KR" : "en-US"); }
function SectionTitle({ id, icon, title, subtitle }: Readonly<{ id: string; icon: React.ReactNode; title: string; subtitle: string }>) { return <div className="min-w-0"><h2 id={id} className="flex items-center gap-2 text-lg font-bold leading-7"><span className="text-accent">{icon}</span>{title}</h2><p className="mt-1 text-sm leading-6 text-muted">{subtitle}</p></div>; }
