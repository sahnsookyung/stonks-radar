import type { ReactNode } from "react";
import { ExternalLink, KeyRound, Radar, ShieldCheck } from "lucide-react";
import { FreshnessBadge, SourceBadge } from "../components/Badge";
import { useLocale } from "../lib/locale";

interface SourceItem {
  name: string;
  url: string;
  category: string;
  signal: string;
  cadence: string;
  access: string;
  status: "active" | "credential_pending" | "candidate";
  risk: "low" | "medium" | "high";
}

const sourceGroups: { title: string; summary: string; sources: SourceItem[] }[] = [
  {
    title: "Official macro and rates",
    summary: "Highest trust inputs for calendars, yields, releases, and canonical macro facts.",
    sources: [
      {
        name: "Federal Reserve",
        url: "https://www.federalreserve.gov/",
        category: "central bank",
        signal: "FOMC calendar, policy statements, H.4.1 balance sheet, supervision notes",
        cadence: "daily/event driven",
        access: "public web/API",
        status: "active",
        risk: "low"
      },
      {
        name: "U.S. Treasury",
        url: "https://home.treasury.gov/resource-center/data-chart-center/interest-rates",
        category: "rates",
        signal: "2Y/3Y/5Y/10Y curves, real yields, TIC capital-flow releases",
        cadence: "daily/monthly",
        access: "public official",
        status: "candidate",
        risk: "low"
      },
      {
        name: "Japan Ministry of Finance JGB rates",
        url: "https://www.mof.go.jp/english/policy/jgbs/reference/interest_rate/index.htm",
        category: "rates",
        signal: "2Y/5Y/10Y Japan government bond yield curve from historical official CSV",
        cadence: "daily; 15-minute cache check is safe",
        access: "public official CSV",
        status: "active",
        risk: "low"
      },
      {
        name: "BLS",
        url: "https://www.bls.gov/developers/",
        category: "macro",
        signal: "CPI, jobs, wages, productivity, import/export prices",
        cadence: "release calendar",
        access: "API key optional",
        status: "active",
        risk: "low"
      },
      {
        name: "EIA",
        url: "https://www.eia.gov/opendata/",
        category: "energy",
        signal: "crude inventories, petroleum balances, natural gas, electricity",
        cadence: "weekly/monthly",
        access: "API key required",
        status: "credential_pending",
        risk: "low"
      }
    ]
  },
  {
    title: "Market data for analytics",
    summary: "Provider stack for prices, portfolio ratios, and market-pulse tiles without exposing secrets.",
    sources: [
      {
        name: "Twelve Data",
        url: "https://twelvedata.com/docs/market-data/time-series",
        category: "market data",
        signal: "split-adjusted daily prices for portfolio Sharpe/Sortino calculations",
        cadence: "user-triggered/cache TTL",
        access: "TWELVE_DATA_API_KEY",
        status: "credential_pending",
        risk: "medium"
      },
      {
        name: "Alpha Vantage",
        url: "https://www.alphavantage.co/documentation/",
        category: "market data",
        signal: "daily close fallback, FX, commodities, indicators",
        cadence: "user-triggered/cache TTL",
        access: "ALPHA_VANTAGE_API_KEY",
        status: "credential_pending",
        risk: "medium"
      },
      {
        name: "Financial Modeling Prep",
        url: "https://site.financialmodelingprep.com/developer/docs/quickstart",
        category: "market/fundamentals",
        signal: "EOD prices, fundamentals, ratios, 13F and insider datasets",
        cadence: "user-triggered/cache TTL",
        access: "FMP_API_KEY",
        status: "credential_pending",
        risk: "medium"
      },
      {
        name: "KRX Open API",
        url: "https://openapi.krx.co.kr/contents/OPP/INFO/service/OPPINFO004.cmd",
        category: "Korea market data",
        signal: "KRX series daily index rows such as KRX 300 and KRX 300 IT",
        cadence: "daily market data; 15-minute cache check stays under free key limits",
        access: "KRX_OPEN_API_AUTH_KEY",
        status: "credential_pending",
        risk: "low"
      },
      {
        name: "iShares EWY",
        url: "https://www.ishares.com/us/products/239681/ishares-msci-south-korea-etf",
        category: "Korea market proxy",
        signal: "EWY public NAV as a Korea equity exposure proxy when direct KRX rows are unavailable",
        cadence: "daily NAV; 15-minute cache check target",
        access: "public page",
        status: "candidate",
        risk: "low"
      }
    ]
  },
  {
    title: "Short pressure and forensic research",
    summary: "High-leverage watchlist for crowded shorts, short sale flow, and public short theses.",
    sources: [
      {
        name: "FINRA short interest",
        url: "https://www.finra.org/filing-reporting/regulatory-filing-systems/short-interest",
        category: "short interest",
        signal: "twice-monthly open short positions, separate from daily short volume",
        cadence: "twice monthly",
        access: "FINRA_API_CLIENT_ID + FINRA_API_CLIENT_SECRET",
        status: "candidate",
        risk: "low"
      },
      {
        name: "FINRA Reg SHO daily short sale volume",
        url: "https://developer.finra.org/docs/api-explorer/query_api-equity-reg_sho_daily_short_sale_volume",
        category: "short volume",
        signal: "daily short sale volume for monitored tickers",
        cadence: "daily",
        access: "FINRA_API_CLIENT_ID + FINRA_API_CLIENT_SECRET",
        status: "candidate",
        risk: "low"
      },
      {
        name: "Muddy Waters / Viceroy / Spruce Point / Kerrisdale / Culper / Blue Orca / Grizzly",
        url: "https://muddywatersresearch.com/research/",
        category: "public short research",
        signal: "new reports, follow-up rebuttals, target-company responses",
        cadence: "15-minute checks when enabled",
        access: "public websites/RSS where available",
        status: "candidate",
        risk: "medium"
      },
    ]
  },
  {
    title: "Overlooked high-leverage signals",
    summary: "Weak or indirect indicators that can matter when paired with official filings and market data.",
    sources: [
      {
        name: "Pentagon.Pizza",
        url: "https://pentagon.pizza/",
        category: "weak OSINT",
        signal: "activity context near defense decision points; never standalone causality",
        cadence: "5-minute target",
        access: "public web",
        status: "candidate",
        risk: "high"
      },
      {
        name: "Defense contract awards / USAspending",
        url: "https://www.defense.gov/News/Contracts/",
        category: "government demand",
        signal: "defense, space, semiconductor, energy and logistics contract awards",
        cadence: "daily",
        access: "public official/API",
        status: "candidate",
        risk: "low"
      },
      {
        name: "SEC EDGAR submissions and companyfacts",
        url: "https://www.sec.gov/search-filings/edgar-application-programming-interfaces",
        category: "filings",
        signal: "latest filings, XBRL facts, insider forms, beneficial ownership",
        cadence: "near realtime",
        access: "SEC_USER_AGENT required",
        status: "active",
        risk: "low"
      },
      {
        name: "OGE public financial disclosures",
        url: "https://www.oge.gov/web/oge.nsf/Officials%20Individual%20Disclosures%20Search%20Collection?OpenForm=",
        category: "filings",
        signal: "Donald J. Trump 278e and 278-T public disclosure filings with legal-use restrictions",
        cadence: "daily; no high-frequency polling because reports are delayed",
        access: "public portal; contact User-Agent",
        status: "active",
        risk: "medium"
      },
      {
        name: "NASA FIRMS / port and customs statistics / ADS-B candidates",
        url: "https://firms.modaps.eosdis.nasa.gov/",
        category: "supply-chain OSINT",
        signal: "facility fire, logistics, shipping and activity anomalies for follow-up",
        cadence: "daily to near realtime",
        access: "mixed public/keyed",
        status: "candidate",
        risk: "medium"
      }
    ]
  }
];

export function SourcesPage() {
  const locale = useLocale();
  const isKo = locale === "ko";

  return (
    <div className="grid min-w-0 gap-7">
      <section className="flex min-w-0 flex-wrap items-end justify-between gap-5">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-accent">
            <ShieldCheck className="h-4 w-4" />
            {isKo ? "출처 레지스트리" : "Source registry"}
          </div>
          <h1 className="safe-text mt-3 max-w-4xl text-3xl font-bold leading-tight sm:text-4xl md:text-5xl">
            {isKo ? "중요 출처와 신호를 한 곳에" : "Every important source, visible by design"}
          </h1>
          <p className="safe-text mt-3 max-w-4xl text-base leading-7 text-muted md:text-lg md:leading-8">
            {isKo
              ? "공식 출처, 시장 데이터, 숏 리서치, 약한 OSINT를 분리해 표시합니다. 약한 신호는 항상 낮은 신뢰도와 검토 게이트를 유지합니다."
              : "Official feeds, market data, short research, and weak OSINT stay separated so users can see what is trusted, what needs credentials, and what is only a prompt for follow-up."}
          </p>
        </div>
        <div className="flex flex-wrap gap-2.5">
          <SourceBadge label="server-side keys only" />
          <SourceBadge label="snapshot-first public pages" />
        </div>
      </section>

      <section className="grid gap-4 md:grid-cols-3">
        <Principle icon={<ShieldCheck className="h-5 w-5" />} title="Trust order" body="Official source beats vendor, vendor beats aggregator, weak OSINT never stands alone." />
        <Principle icon={<KeyRound className="h-5 w-5" />} title="Credentials" body="Provider keys live on OCI as environment variables and are never sent to the browser." />
        <Principle icon={<Radar className="h-5 w-5" />} title="Refresh class" body="Realtime-like sources get shorter polling, but publication remains gated and source-labeled." />
      </section>

      {sourceGroups.map((group) => (
        <section key={group.title} className="min-w-0">
          <div className="mb-3 min-w-0">
            <h2 className="text-xl font-bold">{group.title}</h2>
            <p className="safe-text mt-1 text-sm leading-6 text-muted">{group.summary}</p>
          </div>
          <div className="grid gap-3 lg:grid-cols-2">
            {group.sources.map((source) => (
              <a
                key={`${group.title}-${source.name}`}
                className="panel focus-ring block p-5 hover:border-accent"
                href={source.url}
                target="_blank"
                rel="noreferrer"
              >
                <div className="flex min-w-0 flex-wrap items-start justify-between gap-3">
                  <div className="min-w-0">
                    <h3 className="safe-text font-semibold leading-6">{source.name}</h3>
                    <p className="safe-text mt-2 text-sm leading-6 text-muted">{source.signal}</p>
                  </div>
                  <ExternalLink className="h-4 w-4 text-muted" />
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <FreshnessBadge value={statusToFreshness(source.status)} />
                  <RiskBadge risk={source.risk} />
                  <SourceBadge label={source.category} />
                  <SourceBadge label={source.access} />
                  <SourceBadge label={source.cadence} />
                </div>
              </a>
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function Principle({ icon, title, body }: { icon: ReactNode; title: string; body: string }) {
  return (
    <article className="panel min-w-0 p-5">
      <div className="flex items-center gap-2 font-semibold text-accent">
        {icon}
        {title}
      </div>
      <p className="safe-text mt-2 text-sm leading-6 text-muted">{body}</p>
    </article>
  );
}

function statusToFreshness(status: SourceItem["status"]) {
  if (status === "active") return "fresh";
  if (status === "credential_pending") return "unsupported";
  return "watch";
}

function RiskBadge({ risk }: { risk: SourceItem["risk"] }) {
  const className =
    risk === "high"
      ? "border-warning/50 bg-warning/10 text-warning"
      : risk === "medium"
        ? "border-accent/40 bg-accent/10 text-accent"
        : "border-line bg-panelAlt text-muted";
  return <span className={`badge whitespace-nowrap ${className}`}>risk: {risk}</span>;
}
