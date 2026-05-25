import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Database, ExternalLink, FileText, Sparkles, Users } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import type { AlternativeSignalItem } from "@frw/shared-types";
import { SeverityBadge, SourceBadge } from "../components/Badge";
import { ErrorState, LoadingState } from "../components/LoadingState";
import { SnapshotBanner } from "../components/SnapshotBanner";
import { apiGet } from "../lib/api";
import { useLocale } from "../lib/locale";
import { snapshotQueries } from "../lib/snapshots";

interface DisclosureSummary {
  legal_use_warning: string;
  limitations: string[];
  filings: DisclosureFiling[];
  transactions: DisclosureTransaction[];
  watched_people: WatchedPerson[];
  open_review_items: number;
}

interface DisclosureFiling {
  id: number;
  source: "OGE" | "SEC";
  form_type: string;
  filer_name?: string | null;
  issuer_name?: string | null;
  ticker?: string | null;
  cik?: string | null;
  accession_number?: string | null;
  doc_date?: string | null;
  filed_at?: string | null;
  source_url: string;
  parse_status: string;
  transaction_count: number;
}

interface DisclosureTransaction {
  id: number;
  source: "OGE" | "SEC";
  person_name?: string | null;
  owner_name?: string | null;
  issuer_name?: string | null;
  ticker?: string | null;
  asset_description?: string | null;
  transaction_type?: string | null;
  transaction_code?: string | null;
  transaction_date?: string | null;
  amount_min?: number | null;
  amount_max?: number | null;
  shares?: number | null;
  price?: number | null;
  confidence?: number | null;
  source_url: string;
  form_type: string;
}

interface WatchedPerson {
  canonical_name: string;
  category: string;
  aliases: string[];
  tickers: string[];
  sec_ciks: string[];
  oge_names: string[];
  notes?: string | null;
}

export function TrumpFilingsPage() {
  const locale = useLocale();
  const { t } = useTranslation();
  const snapshotQuery = useQuery({
    queryKey: ["snapshot", "trump-filings", locale],
    queryFn: () => snapshotQueries.home(locale)
  });
  const disclosureQuery = useQuery({
    queryKey: ["trump-disclosures", locale],
    queryFn: () => apiGet<DisclosureSummary>("/api/public/trump-disclosures/summary?limit=80"),
    retry: false
  });

  if (snapshotQuery.isLoading) return <LoadingState />;
  if (snapshotQuery.isError || !snapshotQuery.data) return <ErrorState error={snapshotQuery.error} />;

  const lane = snapshotQuery.data.data.alternative_signals.find((item) => item.key === "trump_filings");
  const summaryItem = lane?.items.find((item) => item.key.endsWith("_ai_summary"));
  const fallbackItems = lane?.items.filter((item) => !item.key.endsWith("_ai_summary")) ?? [];
  const disclosure = disclosureQuery.data;
  const hasApiData = Boolean(disclosure);
  const recentFilings = disclosure?.filings ?? [];
  const transactions = disclosure?.transactions ?? [];

  return (
    <div className="grid min-w-0 gap-7">
      <SnapshotBanner snapshot={snapshotQuery.data} />

      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <h1 className="flex items-center gap-2 text-3xl font-bold leading-tight">
            <FileText className="h-6 w-6 text-accent" />
            {t("trumpFilings")}
          </h1>
          <p className="mt-3 max-w-4xl text-sm leading-6 text-muted">
            {locale === "ko"
              ? "트럼프 관련 공개 주식 공시를 출처 연결형 데이터베이스로 표시합니다. 사설 계좌 활동이나 실시간 거래 신호를 추정하지 않습니다."
              : "A source-linked public disclosure database for Trump-related stock disclosures. It does not infer private brokerage activity or real-time trading signals."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {lane ? <SourceBadge label={lane.cadence} /> : null}
          {hasApiData ? (
            <SourceBadge
              label={
                locale === "ko"
                  ? `검토 ${disclosure?.open_review_items ?? 0}개`
                  : `${disclosure?.open_review_items ?? 0} review items`
              }
            />
          ) : null}
        </div>
      </section>

      <section className="signal-warning p-4">
        <div className="flex items-start gap-3">
          <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0" />
          <p className="text-sm font-semibold leading-6">
            {locale === "ko"
              ? "OGE 공개 재무공개 보고서는 불법 목적, 일반 대중 대상 보도/미디어 배포 외 상업 목적, 신용평가 목적, 모금 권유 목적으로 취득하거나 사용할 수 없습니다."
              : disclosure?.legal_use_warning ??
                "OGE public financial disclosure reports may not be obtained or used for unlawful purposes, commercial purposes other than news/media dissemination to the public, credit-rating purposes, or solicitation purposes."}
          </p>
        </div>
      </section>

      {disclosureQuery.isError ? (
        <section className="panel p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-warning">
            <AlertTriangle className="h-4 w-4" />
            {locale === "ko" ? "공개 공시 API 대기 중" : "Disclosure API pending"}
          </div>
          <p className="mt-2 text-sm leading-6 text-muted">
            {locale === "ko"
              ? "백엔드 공시 데이터베이스를 읽을 수 없어 스냅샷 요약으로 대체합니다."
              : "The backend disclosure database is not readable from this session, so the page is falling back to the static snapshot digest."}
          </p>
          <div className="mt-5 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {fallbackItems.map((item) => (
              <FallbackCard key={item.key} item={item} locale={locale} />
            ))}
          </div>
        </section>
      ) : null}

      {hasApiData ? (
        <>
          <section className="grid gap-3 md:grid-cols-3">
            <StatCard
              icon={<Database className="h-5 w-5" />}
              label={locale === "ko" ? "공시" : "Filings"}
              value={String(recentFilings.length)}
              detail={locale === "ko" ? "OGE + SEC 원문 연결" : "OGE + SEC source linked"}
            />
            <StatCard
              icon={<FileText className="h-5 w-5" />}
              label={locale === "ko" ? "거래 행" : "Transaction Rows"}
              value={String(transactions.length)}
              detail={locale === "ko" ? "확정 공개자료만 표시" : "Only legally public rows"}
            />
            <StatCard
              icon={<Users className="h-5 w-5" />}
              label={locale === "ko" ? "감시 대상" : "Watchlist"}
              value={String(disclosure?.watched_people.length ?? 0)}
              detail={locale === "ko" ? "성인 가족은 SEC 기준만" : "Adult family is SEC-only"}
            />
          </section>

          <section className="panel p-5">
            <SectionHeader
              icon={<FileText className="h-5 w-5" />}
              title={locale === "ko" ? "최근 공개 거래" : "Recent Public Transactions"}
              subtitle={
                locale === "ko"
                  ? "OGE 행은 금액 범위이며, SEC Form 4는 신고된 보유권 변동입니다."
                  : "OGE rows are amount ranges; SEC Form 4 rows are reported beneficial-ownership changes."
              }
            />
            {transactions.length ? (
              <div className="mt-4 grid gap-3">
                {transactions.slice(0, 24).map((transaction) => (
                  <TransactionRow key={transaction.id} transaction={transaction} locale={locale} />
                ))}
              </div>
            ) : (
              <EmptyState
                text={
                  locale === "ko"
                    ? "아직 파싱된 거래 행이 없습니다. 원문 공시와 검토 대기열은 아래에 표시됩니다."
                    : "No parsed transaction rows yet. Source filings and review status are still shown below."
                }
              />
            )}
          </section>

          <section className="panel p-5">
            <SectionHeader
              icon={<Database className="h-5 w-5" />}
              title={locale === "ko" ? "출처 공시" : "Source Filings"}
              subtitle={
                locale === "ko"
                  ? "각 공시는 원문으로 바로 이동할 수 있으며 파싱 상태를 함께 표시합니다."
                  : "Every filing links to the original source and carries parser status."
              }
            />
            <div className="mt-4 grid gap-3 md:grid-cols-2">
              {recentFilings.map((filing) => (
                <FilingRow key={`${filing.source}-${filing.id}`} filing={filing} locale={locale} />
              ))}
            </div>
          </section>

          <section className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(300px,420px)]">
            <div className="panel p-5">
              <SectionHeader
                icon={<AlertTriangle className="h-5 w-5" />}
                title={locale === "ko" ? "하드 제한" : "Hard Limitations"}
                subtitle={
                  locale === "ko"
                    ? "이 탭이 말할 수 없는 것도 같이 보여줍니다."
                    : "The page keeps what it cannot know visible."
                }
              />
              <ul className="mt-4 grid gap-2 text-sm leading-6 text-muted">
                {(disclosure?.limitations ?? []).map((limitation) => (
                  <li key={limitation} className="rounded-md border border-line bg-panelAlt px-3 py-2">
                    {locale === "ko" ? translateLimitation(limitation) : limitation}
                  </li>
                ))}
              </ul>
            </div>

            <div className="panel p-5">
              <SectionHeader
                icon={<Users className="h-5 w-5" />}
                title={locale === "ko" ? "감시 범위" : "Watch Scope"}
                subtitle={
                  locale === "ko"
                    ? "성인 가족은 공개 SEC 공시가 있을 때만 포함됩니다."
                    : "Adult family members are included only when public SEC filings name them."
                }
              />
              <div className="mt-4 grid gap-3">
                {(disclosure?.watched_people ?? []).map((person) => (
                  <WatchPerson key={person.canonical_name} person={person} />
                ))}
              </div>
            </div>
          </section>
        </>
      ) : disclosureQuery.isLoading ? (
        <LoadingState />
      ) : null}

      {summaryItem ? (
        <section className="panel p-5">
          <div className="flex items-center gap-2 text-sm font-semibold text-accent">
            <Sparkles className="h-4 w-4" />
            {summaryItem.label}
          </div>
          <p className="mt-2 text-sm leading-6 text-muted">{summaryItem.detail}</p>
          <div className="mt-3">
            <SeverityBadge value={summaryItem.severity} />
          </div>
        </section>
      ) : null}
    </div>
  );
}

function SectionHeader({
  icon,
  title,
  subtitle
}: {
  icon: ReactNode;
  title: string;
  subtitle: string;
}) {
  return (
    <div>
      <h2 className="flex items-center gap-2 text-lg font-bold leading-7">
        <span className="text-accent">{icon}</span>
        {title}
      </h2>
      <p className="mt-1 text-sm leading-6 text-muted">{subtitle}</p>
    </div>
  );
}

function StatCard({
  icon,
  label,
  value,
  detail
}: {
  icon: ReactNode;
  label: string;
  value: string;
  detail: string;
}) {
  return (
    <article className="panel p-4">
      <div className="flex items-center gap-2 text-sm font-semibold text-muted">
        <span className="text-accent">{icon}</span>
        {label}
      </div>
      <div className="mt-3 text-3xl font-bold">{value}</div>
      <p className="mt-1 text-sm leading-6 text-muted">{detail}</p>
    </article>
  );
}

function TransactionRow({
  transaction,
  locale
}: {
  transaction: DisclosureTransaction;
  locale: "en" | "ko";
}) {
  const value = transaction.source === "OGE" ? formatOgeAmount(transaction) : formatSecAmount(transaction);
  return (
    <a
      className="focus-ring grid gap-3 rounded-md border border-line bg-panelAlt p-4 hover:border-accent md:grid-cols-[minmax(0,1fr)_170px_120px]"
      href={transaction.source_url}
      target="_blank"
      rel="noreferrer"
    >
      <div className="min-w-0">
        <div className="flex min-w-0 flex-wrap items-center gap-2">
          <span className="badge border-accent/40 bg-accentSoft text-accent">{transaction.source}</span>
          {transaction.ticker ? <span className="badge border-line bg-panel">{transaction.ticker}</span> : null}
          <span className="text-xs font-semibold uppercase leading-5 text-muted">
            {transaction.form_type}
          </span>
        </div>
        <h3 className="mt-2 truncate text-sm font-semibold leading-5">
          {transaction.issuer_name || transaction.asset_description || "Disclosure row"}
        </h3>
        <p className="mt-1 line-clamp-2 text-xs leading-5 text-muted">{transaction.asset_description}</p>
      </div>
      <div>
        <div className="text-xs font-semibold uppercase leading-5 text-muted">
          {locale === "ko" ? "거래" : "Transaction"}
        </div>
        <div className="mt-1 text-sm font-bold leading-5">
          {transaction.transaction_type || transaction.transaction_code || "reported"}
        </div>
        <div className="mt-1 text-xs leading-5 text-muted">{transaction.transaction_date || "date pending"}</div>
      </div>
      <div>
        <div className="text-xs font-semibold uppercase leading-5 text-muted">
          {locale === "ko" ? "규모" : "Size"}
        </div>
        <div className="mt-1 text-sm font-bold leading-5">{value}</div>
        <div className="mt-1 flex items-center gap-1 text-xs font-semibold leading-5 text-accent">
          {locale === "ko" ? "원문" : "Source"}
          <ExternalLink className="h-3.5 w-3.5" />
        </div>
      </div>
    </a>
  );
}

function FilingRow({ filing, locale }: { filing: DisclosureFiling; locale: "en" | "ko" }) {
  return (
    <a
      className="focus-ring block rounded-md border border-line bg-panelAlt p-4 hover:border-accent"
      href={filing.source_url}
      target="_blank"
      rel="noreferrer"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="badge border-accent/40 bg-accentSoft text-accent">{filing.source}</span>
            <span className="badge border-line bg-panel">{filing.form_type}</span>
            {filing.ticker ? <span className="badge border-line bg-panel">{filing.ticker}</span> : null}
          </div>
          <h3 className="mt-3 truncate text-sm font-semibold leading-5">
            {filing.issuer_name || filing.filer_name || filing.accession_number || "Public filing"}
          </h3>
          <p className="mt-1 text-xs leading-5 text-muted">
            {filing.doc_date || filing.filed_at || (locale === "ko" ? "날짜 대기" : "date pending")}
          </p>
        </div>
        <div className="shrink-0 text-right">
          <div className="text-xs font-semibold leading-5 text-muted">{filing.parse_status}</div>
          <div className="mt-1 text-sm font-bold leading-5">{filing.transaction_count}</div>
        </div>
      </div>
    </a>
  );
}

function WatchPerson({ person }: { person: WatchedPerson }) {
  const tags = [...person.tickers, ...person.sec_ciks].filter(Boolean);
  return (
    <article className="rounded-md border border-line bg-panelAlt p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-sm font-semibold leading-5">{person.canonical_name}</h3>
        <span className="badge border-line bg-panel">{person.category}</span>
      </div>
      {tags.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {tags.map((tag) => (
            <span key={tag} className="rounded border border-line px-2 py-1 text-xs text-muted">
              {tag}
            </span>
          ))}
        </div>
      ) : null}
      {person.notes ? <p className="mt-2 text-xs leading-5 text-muted">{person.notes}</p> : null}
    </article>
  );
}

function FallbackCard({ item, locale }: { item: AlternativeSignalItem; locale: "en" | "ko" }) {
  const content = (
    <>
      <div className="flex items-start justify-between gap-3">
        <h3 className="min-w-0 text-sm font-semibold leading-5">{item.label}</h3>
        <div className="shrink-0 text-xs font-semibold leading-5 text-accent">{item.value}</div>
      </div>
      <p className="mt-2 text-xs leading-5 text-muted">{item.detail}</p>
      {item.source_url ? (
        <div className="mt-3 flex items-center gap-1 text-xs font-semibold leading-5 text-accent">
          {locale === "ko" ? "출처" : "Source"}
          <ExternalLink className="h-3.5 w-3.5" />
        </div>
      ) : null}
    </>
  );
  const className = "focus-ring block min-h-[160px] rounded-md border border-line bg-panelAlt p-4 hover:border-accent";
  if (item.source_url) {
    return (
      <a className={className} href={item.source_url} target="_blank" rel="noreferrer">
        {content}
      </a>
    );
  }
  return <article className={className}>{content}</article>;
}

function EmptyState({ text }: { text: string }) {
  return <div className="mt-4 rounded-md border border-dashed border-line p-5 text-sm leading-6 text-muted">{text}</div>;
}

function formatOgeAmount(transaction: DisclosureTransaction) {
  if (transaction.amount_min == null && transaction.amount_max == null) return "range pending";
  if (transaction.amount_max == null) return `>${formatMoney(transaction.amount_min ?? 0)}`;
  return `${formatMoney(transaction.amount_min ?? 0)}-${formatMoney(transaction.amount_max)}`;
}

function formatSecAmount(transaction: DisclosureTransaction) {
  if (transaction.shares == null && transaction.price == null) return transaction.transaction_code || "reported";
  const shares = transaction.shares == null ? "" : `${formatNumber(transaction.shares)} sh`;
  const price = transaction.price == null ? "" : `@ ${formatMoney(transaction.price)}`;
  return [shares, price].filter(Boolean).join(" ");
}

function formatMoney(value: number) {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 0
  }).format(value);
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
}

function translateLimitation(value: string) {
  const translations: Record<string, string> = {
    "This is a source-linked public disclosure database, not a copy-trading signal.":
      "이것은 출처 연결형 공개 공시 데이터베이스이며 복사 매매 신호가 아닙니다.",
    "OGE data is delayed; Form 278-T may be filed up to 45 days after a transaction.":
      "OGE 데이터는 지연됩니다. Form 278-T는 거래 후 최대 45일 뒤 제출될 수 있습니다.",
    "OGE values are amount ranges, not exact trade sizes.":
      "OGE 금액은 정확한 거래 규모가 아니라 범위입니다.",
    "OGE covers Donald J. Trump, spouse, and dependent-child transactions only where reportable in his filings.":
      "OGE는 도널드 J. 트럼프 본인, 배우자, 피부양 자녀 거래 중 그의 공시에 보고되는 항목만 포함합니다.",
    "Adult family members are tracked only when they appear in SEC filings or issuer disclosures.":
      "성인 가족 구성원은 SEC 공시 또는 발행사 공시에 등장할 때만 추적합니다.",
    "SEC Form 144 is proposed sale intent, not proof the sale occurred.":
      "SEC Form 144는 매도 예정 통지이며 실제 매도 발생의 증거가 아닙니다.",
    "Schedule 13D/G is large beneficial ownership disclosure, not every trade.":
      "Schedule 13D/G는 대규모 수익소유 공시이며 모든 거래를 뜻하지 않습니다.",
    "Ticker extraction from PDFs can be wrong; every row links back to the source filing.":
      "PDF에서 추출한 티커는 틀릴 수 있으므로 모든 행은 원문 공시에 연결됩니다."
  };
  return translations[value] ?? value;
}
