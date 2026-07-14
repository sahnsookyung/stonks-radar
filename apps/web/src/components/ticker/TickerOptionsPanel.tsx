import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Activity, ExternalLink, KeyRound, ShieldCheck, Trash2 } from "lucide-react";
import {
  connectProvider,
  deleteProviderConnection,
  getPrivateOptions,
  getProviderConnection,
  memberSignInUrl,
  TickerApiError,
  type PrivateOptionRow
} from "../../lib/tickerApi";
import type { TrackedTicker } from "../../lib/trackedTickers";

export function TickerOptionsPanel({
  ticker,
  locale,
  isSignedIn
}: Readonly<{ ticker: TrackedTicker; locale: "en" | "ko"; isSignedIn: boolean }>) {
  const isKo = locale === "ko";
  const [expiration, setExpiration] = useState("");
  const [token, setToken] = useState("");
  const queryClient = useQueryClient();
  const connectionQuery = useQuery({
    queryKey: ["ticker-provider-connection"],
    queryFn: ({ signal }) => getProviderConnection(signal),
    enabled: isSignedIn,
    retry: false
  });
  const optionsQuery = useQuery({
    queryKey: ["ticker-private-options", ticker.symbol, expiration],
    queryFn: ({ signal }) => getPrivateOptions(ticker.symbol, expiration || undefined, signal),
    enabled: isSignedIn && connectionQuery.data?.status === "verified",
    retry: false
  });
  const connectMutation = useMutation({
    mutationFn: () => connectProvider(token),
    onSuccess: async () => {
      setToken("");
      await queryClient.invalidateQueries({ queryKey: ["ticker-provider-connection"] });
      await queryClient.invalidateQueries({ queryKey: ["ticker-private-options", ticker.symbol] });
    }
  });
  const deleteMutation = useMutation({
    mutationFn: () => deleteProviderConnection(),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["ticker-provider-connection"] });
      queryClient.removeQueries({ queryKey: ["ticker-private-options"] });
    }
  });

  const rows = useMemo(() => pairOptionRows(optionsQuery.data?.chain ?? []), [optionsQuery.data?.chain]);
  const expirations = useMemo(
    () => Array.from(new Set((optionsQuery.data?.chain ?? []).map((row) => row.expiration).filter((value): value is string => Boolean(value)))).sort(),
    [optionsQuery.data?.chain]
  );
  const summary = useMemo(() => summarizeOptions(optionsQuery.data?.chain ?? []), [optionsQuery.data?.chain]);
  const state = optionState(isSignedIn, connectionQuery.data?.status, connectionQuery.error, optionsQuery.data?.status, optionsQuery.error, optionsQuery.isLoading);
  const asOf = formatAsOf(optionsQuery.data?.as_of, locale);
  const stale = isStale(optionsQuery.data?.as_of);

  return (
    <section className="panel min-w-0 p-5" aria-labelledby="ticker-options-heading">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 id="ticker-options-heading" className="flex items-center gap-2 text-lg font-bold leading-7">
            <Activity className="h-5 w-5 text-accent" />
            {isKo ? "개인 옵션 워크스페이스" : "Private Options Workspace"}
          </h2>
          <p className="mt-1 text-sm leading-6 text-muted">
            {isKo ? "검증된 개인 공급자 연결의 지연 데이터를 이 회원 세션에만 표시합니다." : "Delayed data from a verified personal provider connection is visible only to this member session."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <StateBadge state={state} locale={locale} />
          {optionsQuery.data ? <span className="badge border-line bg-panelAlt text-muted">{optionsQuery.data.delay}</span> : null}
          {optionsQuery.data ? <span className={`badge ${stale ? "border-warning/50 bg-warning/10 text-warning" : "border-success/50 bg-success/10 text-success"}`}>{asOf}</span> : null}
        </div>
      </div>

      <OptionAccessState
        state={state}
        locale={locale}
        ticker={ticker}
        token={token}
        onTokenChange={setToken}
        onConnect={() => connectMutation.mutate()}
        connecting={connectMutation.isPending}
        connectionError={connectMutation.error}
      />

      {state === "ready" || state === "empty" ? (
        <>
          <div className="mt-4 flex flex-wrap items-end justify-between gap-3">
            <label htmlFor="ticker-option-expiration" className="grid gap-1 text-xs font-semibold uppercase text-muted">
              {isKo ? "만기" : "Expiration"}
              <select
                id="ticker-option-expiration"
                className="input-control min-h-11 min-w-[190px]"
                value={expiration}
                onChange={(event) => setExpiration(event.target.value)}
              >
                <option value="">{isKo ? "가장 가까운 만기" : "Nearest available"}</option>
                {expirations.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
            </label>
            <button type="button" className="secondary-action" onClick={() => deleteMutation.mutate()} disabled={deleteMutation.isPending}>
              <Trash2 className="h-4 w-4" />
              {isKo ? "연결 삭제" : "Remove connection"}
            </button>
          </div>
          {stale ? <div className="signal-warning mt-4 p-4 text-sm leading-6">{isKo ? "공급자 시각이 48시간을 초과했습니다. 투자 판단 전에 원문 시각을 확인하세요." : "The provider as-of time is more than 48 hours old. Verify the source timestamp before relying on it."}</div> : null}
          <div className="mt-4 grid gap-3 md:grid-cols-3 xl:grid-cols-4">
            {summaryCards(summary, expiration || expirations[0], locale).map((field) => (
              <article key={field.label} className="rounded-md border border-line bg-panelAlt p-4">
                <div className="text-xs font-semibold uppercase leading-5 text-muted">{field.label}</div>
                <div className="mt-2 text-xl font-bold leading-tight">{field.value}</div>
                <p className="mt-2 text-xs leading-5 text-muted">{field.detail}</p>
              </article>
            ))}
          </div>
          <div className="mt-5 table-surface" data-allow-horizontal-scroll aria-label={isKo ? "지연 옵션 체인 표" : "Delayed options chain table"}>
            <table className="min-w-full text-left text-sm">
              <caption className="sr-only">{isKo ? "최대 100개 행사가의 지연 옵션 체인" : "Delayed option chain bounded to 100 strikes"}</caption>
              <thead className="table-head"><tr>{["Strike", "Call bid", "Call ask", "Call vol", "Call OI", "Call IV", "Call delta", "Put bid", "Put ask", "Put vol", "Put OI", "Put IV", "Put delta"].map((heading) => <th key={heading} scope="col" className="px-3 py-3">{heading}</th>)}</tr></thead>
              <tbody>
                {rows.length ? rows.slice(0, 100).map((row) => (
                  <tr key={row.strike} className="border-t border-line">
                    <th scope="row" className="px-3 py-3 font-semibold">{formatNumber(row.strike)}</th>
                    <OptionCells row={row.call} />
                    <OptionCells row={row.put} />
                  </tr>
                )) : <tr className="border-t border-line"><td colSpan={13} className="px-3 py-4 text-muted">{isKo ? "선택한 만기에 체인 행이 없습니다." : "No chain rows are available for the selected expiration."}</td></tr>}
              </tbody>
            </table>
          </div>
        </>
      ) : null}

      <a href={`https://www.tradingview.com/chart/?symbol=${encodeURIComponent(ticker.tradingViewSymbol)}`} target="_blank" rel="noreferrer" className="secondary-action mt-5">
        <ExternalLink className="h-4 w-4" />{isKo ? "공급자 소유 차트" : "Provider-owned chart"}
      </a>
    </section>
  );
}

type OptionState = "signed_out" | "entitlement_required" | "loading" | "provider_error" | "empty" | "ready";

function optionState(
  signedIn: boolean,
  connection: string | undefined,
  connectionError: unknown,
  dataStatus: string | undefined,
  dataError: unknown,
  loading: boolean
): OptionState {
  if (!signedIn) return "signed_out";
  if (connectionError instanceof TickerApiError && [403, 404].includes(connectionError.status)) return "entitlement_required";
  if (connection !== "verified") return connection === undefined && !connectionError ? "loading" : "entitlement_required";
  if (loading) return "loading";
  if (dataError instanceof TickerApiError && [401, 403].includes(dataError.status)) return "entitlement_required";
  if (dataError) return "provider_error";
  return dataStatus === "empty" ? "empty" : "ready";
}

function OptionAccessState(props: Readonly<{
  state: OptionState;
  locale: "en" | "ko";
  ticker: TrackedTicker;
  token: string;
  onTokenChange: (value: string) => void;
  onConnect: () => void;
  connecting: boolean;
  connectionError: unknown;
}>) {
  const isKo = props.locale === "ko";
  if (props.state === "ready" || props.state === "empty") return null;
  if (props.state === "signed_out") return (
    <div className="signal-warning mt-4 p-4 text-sm leading-6">
      <p>{isKo ? "옵션 초안은 로컬에 보관할 수 있지만 지연 체인과 백그라운드 알림은 회원 로그인이 필요합니다." : "Local alert drafts are available, but delayed chains and background evaluation require member sign-in."}</p>
      <a className="primary-action mt-3" href={memberSignInUrl(globalThis.window.location.pathname + globalThis.window.location.search)}><ShieldCheck className="h-4 w-4" />{isKo ? "Google로 로그인" : "Sign in with Google"}</a>
    </div>
  );
  if (props.state === "loading") return <div className="mt-4 rounded-md border border-line bg-panelAlt p-4 text-sm text-muted">{isKo ? "연결과 체인을 확인하는 중입니다." : "Checking provider connection and chain."}</div>;
  if (props.state === "provider_error") return <div className="signal-danger mt-4 p-4 text-sm leading-6">{isKo ? "개인 공급자가 응답하지 않았습니다. 토큰, 할당량, 공급자 상태를 확인하세요." : "The private provider did not respond. Check the token, quota, and provider status."}</div>;
  return (
    <div className="signal-warning mt-4 p-4 text-sm leading-6">
      <p>{isKo ? "개인 MarketData.app 토큰은 서버에서 AES-256-GCM으로 암호화되며 공개 API나 스냅샷에 포함되지 않습니다. 생산 기능은 위임 사용 승인이 있어야 활성화됩니다." : "Your MarketData.app token is encrypted server-side with AES-256-GCM and never enters public APIs or snapshots. Production enablement requires delegated-use approval."}</p>
      <div className="mt-3 flex flex-col gap-2 sm:flex-row">
        <label htmlFor="ticker-provider-token" className="sr-only">{isKo ? "개인 공급자 토큰" : "Private provider token"}</label>
        <input id="ticker-provider-token" type="password" autoComplete="off" className="input-control min-h-11 flex-1" value={props.token} onChange={(event) => props.onTokenChange(event.target.value)} placeholder={isKo ? "개인 API 토큰" : "Personal API token"} />
        <button type="button" className="primary-action" disabled={!props.token.trim() || props.connecting} onClick={props.onConnect}><KeyRound className="h-4 w-4" />{props.connecting ? (isKo ? "검증 중" : "Verifying") : (isKo ? "검증하고 연결" : "Verify and connect")}</button>
      </div>
      {props.connectionError ? <p role="alert" className="mt-2 text-danger">{props.connectionError instanceof Error ? props.connectionError.message : (isKo ? "연결 실패" : "Connection failed")}</p> : null}
    </div>
  );
}

function StateBadge({ state, locale }: Readonly<{ state: OptionState; locale: "en" | "ko" }>) {
  const labels: Record<OptionState, [string, string]> = {
    signed_out: ["Sign-in required", "로그인 필요"], entitlement_required: ["Entitlement required", "권한 필요"], loading: ["Loading", "로딩"], provider_error: ["Provider error", "공급자 오류"], empty: ["Empty", "비어 있음"], ready: ["Ready", "준비"]
  };
  return <span className="badge border-line bg-panelAlt text-muted">{labels[state][locale === "ko" ? 1 : 0]}</span>;
}

function pairOptionRows(chain: PrivateOptionRow[]) {
  const pairs = new Map<number, { strike: number; call?: PrivateOptionRow; put?: PrivateOptionRow }>();
  for (const row of chain) {
    const strike = numeric(row.strike);
    if (!Number.isFinite(strike)) continue;
    const pair = pairs.get(strike) ?? { strike };
    if (String(row.side).toLowerCase().startsWith("c")) pair.call = row;
    if (String(row.side).toLowerCase().startsWith("p")) pair.put = row;
    pairs.set(strike, pair);
  }
  return Array.from(pairs.values()).sort((left, right) => left.strike - right.strike);
}

function summarizeOptions(chain: PrivateOptionRow[]) {
  const underlying = chain.map((row) => numeric(row.underlying_price)).find(Number.isFinite) ?? Number.NaN;
  const paired = pairOptionRows(chain);
  const atm = paired.reduce<typeof paired[number] | undefined>((best, row) => !best || Math.abs(row.strike - underlying) < Math.abs(best.strike - underlying) ? row : best, undefined);
  const callVolume = sum(chain.filter((row) => String(row.side).toLowerCase().startsWith("c")), "volume");
  const putVolume = sum(chain.filter((row) => String(row.side).toLowerCase().startsWith("p")), "volume");
  const callOi = sum(chain.filter((row) => String(row.side).toLowerCase().startsWith("c")), "open_interest");
  const putOi = sum(chain.filter((row) => String(row.side).toLowerCase().startsWith("p")), "open_interest");
  const straddle = midpoint(atm?.call) + midpoint(atm?.put);
  const calls = chain.filter((row) => String(row.side).toLowerCase().startsWith("c"));
  const puts = chain.filter((row) => String(row.side).toLowerCase().startsWith("p"));
  return {
    underlying, atm, callVolume, putVolume, callOi, putOi, straddle,
    highestCallVolume: highestBy(calls, "volume"),
    highestPutVolume: highestBy(puts, "volume"),
    highestCallOi: highestBy(calls, "open_interest"),
    highestPutOi: highestBy(puts, "open_interest")
  };
}

function summaryCards(summary: ReturnType<typeof summarizeOptions>, expiration: string | undefined, locale: "en" | "ko") {
  const isKo = locale === "ko";
  const atmIvValues = [numeric(summary.atm?.call?.implied_volatility), numeric(summary.atm?.put?.implied_volatility)].filter(Number.isFinite);
  const atmIv = atmIvValues.length ? atmIvValues.reduce((total, value) => total + value, 0) / atmIvValues.length : Number.NaN;
  return [
    { label: isKo ? "만기" : "Expiration", value: expiration || (isKo ? "없음" : "Unavailable"), detail: expiration ? `${daysToExpiry(expiration)} ${isKo ? "일 남음" : "days to expiry"}` : (isKo ? "선택한 지연 체인" : "Selected delayed chain") },
    { label: "ATM IV", value: Number.isFinite(atmIv) ? `${(atmIv * (atmIv <= 3 ? 100 : 1)).toFixed(1)}%` : "Unavailable", detail: isKo ? "콜/풋 평균" : "Call/put average" },
    { label: isKo ? "ATM 스트래들" : "ATM straddle", value: money(summary.straddle), detail: isKo ? "bid/ask 중간값" : "Bid/ask midpoint" },
    { label: isKo ? "예상 변동" : "Expected move", value: Number.isFinite(summary.underlying) && summary.underlying ? `${((summary.straddle / summary.underlying) * 100).toFixed(1)}%` : "Unavailable", detail: isKo ? "스트래들/기초자산" : "Straddle / underlying" },
    { label: isKo ? "콜 거래량 / OI" : "Call volume / OI", value: `${formatNumber(summary.callVolume)} / ${formatNumber(summary.callOi)}`, detail: isKo ? "체인 합계" : "Chain totals" },
    { label: isKo ? "풋 거래량 / OI" : "Put volume / OI", value: `${formatNumber(summary.putVolume)} / ${formatNumber(summary.putOi)}`, detail: isKo ? "체인 합계" : "Chain totals" },
    { label: isKo ? "풋/콜 비율" : "Put/call ratios", value: `${ratio(summary.putVolume, summary.callVolume)} vol / ${ratio(summary.putOi, summary.callOi)} OI`, detail: isKo ? "거래량과 미결제약정" : "Volume and open interest" },
    { label: isKo ? "최대 거래량 행사가" : "Highest-volume strikes", value: `C ${strike(summary.highestCallVolume)} / P ${strike(summary.highestPutVolume)}`, detail: isKo ? "콜과 풋" : "Calls and puts" },
    { label: isKo ? "최대 OI 행사가" : "Highest-OI strikes", value: `C ${strike(summary.highestCallOi)} / P ${strike(summary.highestPutOi)}`, detail: isKo ? "콜과 풋" : "Calls and puts" }
  ];
}

function OptionCells({ row }: Readonly<{ row?: PrivateOptionRow }>) {
  return <><td className="px-3 py-3">{money(numeric(row?.bid))}</td><td className="px-3 py-3">{money(numeric(row?.ask))}</td><td className="px-3 py-3">{formatNumber(numeric(row?.volume))}</td><td className="px-3 py-3">{formatNumber(numeric(row?.open_interest))}</td><td className="px-3 py-3">{formatIv(row?.implied_volatility)}</td><td className="px-3 py-3">{formatNumber(numeric(row?.delta))}</td></>;
}

function sum(rows: PrivateOptionRow[], key: "volume" | "open_interest") { return rows.reduce((total, row) => total + (numeric(row[key]) || 0), 0); }
function highestBy(rows: PrivateOptionRow[], key: "volume" | "open_interest") { return [...rows].sort((left, right) => numeric(right[key]) - numeric(left[key]))[0]; }
function strike(row?: PrivateOptionRow) { return row ? formatNumber(numeric(row.strike)) : "—"; }
function daysToExpiry(value: string) { const expiry = new Date(`${value}T00:00:00Z`); return Number.isNaN(expiry.getTime()) ? "—" : Math.max(0, Math.ceil((expiry.getTime() - Date.now()) / 86_400_000)); }
function midpoint(row?: PrivateOptionRow) { const bid = numeric(row?.bid); const ask = numeric(row?.ask); return Number.isFinite(bid) && Number.isFinite(ask) ? (bid + ask) / 2 : numeric(row?.last) || 0; }
function numeric(value: unknown) { const number = Number(value); return Number.isFinite(number) ? number : Number.NaN; }
function ratio(top: number, bottom: number) { return bottom > 0 ? (top / bottom).toFixed(2) : "—"; }
function money(value: number) { return Number.isFinite(value) ? new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(value) : "—"; }
function formatNumber(value: number) { return Number.isFinite(value) ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value) : "—"; }
function formatIv(value: unknown) { const number = numeric(value); return Number.isFinite(number) ? `${(number * (number <= 3 ? 100 : 1)).toFixed(1)}%` : "—"; }
function formatAsOf(value: string | number | null | undefined, locale: "en" | "ko") { const date = dateFrom(value); return date ? `${locale === "ko" ? "기준" : "As of"} ${date.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}` : (locale === "ko" ? "기준 시각 없음" : "As-of unavailable"); }
function isStale(value: string | number | null | undefined) { const date = dateFrom(value); return Boolean(date && Date.now() - date.getTime() > 48 * 60 * 60_000); }
function dateFrom(value: string | number | null | undefined) { if (value == null) return null; const numericValue = typeof value === "number" ? value * (value < 10_000_000_000 ? 1000 : 1) : value; const date = new Date(numericValue); return Number.isNaN(date.getTime()) ? null : date; }
