import { Link, useRouterState } from "@tanstack/react-router";
import { Activity, Calculator, Database, FileText, Globe2, LayoutDashboard, Lock, Map, Newspaper, Scale, SearchCheck, ShieldAlert, TrendingUp } from "lucide-react";
import { useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { alternateLocale, asLocale, useLocale } from "../lib/locale";

const sectorLinks = [
  ["space", "Space", "우주"],
  ["quantum", "Quantum", "양자"],
  ["semiconductors", "Semiconductors", "반도체"],
  ["oil-energy", "Oil/Energy", "석유/에너지"],
  ["big-tech", "Big Tech", "빅테크"]
];

const countryLinks = [
  ["USA", "US", "미국"],
  ["KOR", "Korea", "한국"],
  ["JPN", "Japan", "일본"],
  ["CHN", "China", "중국"],
  ["EUROZONE", "Eurozone", "유로존"]
];

export function Shell({ children }: { children: React.ReactNode }) {
  const locale = useLocale();
  const { t } = useTranslation();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const other = alternateLocale(locale);
  const alternatePath = pathname.replace(/^\/(en|ko)(?=\/|$)/, `/${other}`);
  const activePrimaryNavKey = getActivePrimaryNavKey(pathname);
  const primaryNavRefs = useRef<Record<string, HTMLAnchorElement | null>>({});

  useEffect(() => {
    const node = activePrimaryNavKey ? primaryNavRefs.current[activePrimaryNavKey] : null;
    if (!node) return;
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    node.scrollIntoView({
      block: "nearest",
      inline: "center",
      behavior: prefersReducedMotion ? "auto" : "smooth"
    });
  }, [activePrimaryNavKey]);

  const registerPrimaryNavRef = (key: string, element: HTMLAnchorElement | null) => {
    primaryNavRefs.current[key] = element;
  };

  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="sticky top-0 z-20 overflow-x-hidden border-b border-line bg-panel/95 shadow-insetLine backdrop-blur [contain:paint]">
        <div className="mx-auto flex max-w-7xl items-center gap-2 px-3 py-2 sm:px-4 md:flex-wrap md:justify-between md:gap-4 md:py-3 lg:px-6">
          <Link to="/$locale" params={{ locale }} className="focus-ring flex min-h-11 min-w-0 shrink-0 items-center gap-2 md:gap-3">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-accent text-paper shadow-insetLine md:h-10 md:w-10">
              <SearchCheck className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="truncate text-sm font-bold leading-5 sm:text-base">{t("appName")}</div>
              <div className="sr-only text-xs text-muted md:not-sr-only md:block">{t("noAdvice")}</div>
            </div>
          </Link>
          <nav
            className="scroll-fade-x -mr-3 flex min-w-0 flex-1 items-center gap-1 overflow-x-auto py-1 pr-3 text-sm [contain:paint] md:mr-0 md:basis-auto md:flex-wrap md:justify-end md:overflow-visible md:pr-0"
            data-allow-horizontal-scroll
            aria-label={locale === "ko" ? "기본 탐색" : "Primary navigation"}
          >
            <NavLink navKey="dashboard" registerRef={registerPrimaryNavRef} to="/$locale" params={{ locale }} icon={<LayoutDashboard />} label={t("dashboard")} />
            <NavLink navKey="map" registerRef={registerPrimaryNavRef} to="/$locale/map" params={{ locale }} icon={<Map />} label={t("map")} />
            <NavLink navKey="calendar" registerRef={registerPrimaryNavRef} to="/$locale/calendar" params={{ locale }} icon={<Activity />} label={t("calendar")} />
            <NavLink navKey="market-pulse" registerRef={registerPrimaryNavRef} to="/$locale/market-pulse" params={{ locale }} icon={<TrendingUp />} label={t("marketPulse")} />
            <NavLink navKey="portfolio" registerRef={registerPrimaryNavRef} to="/$locale/portfolio" params={{ locale }} icon={<Calculator />} label={t("portfolio")} />
            <NavLink navKey="tickers" registerRef={registerPrimaryNavRef} to="/$locale/tickers/$symbol" params={{ locale, symbol: "NVDA" }} icon={<TrendingUp />} label={t("tickers")} />
            <NavLink navKey="news" registerRef={registerPrimaryNavRef} to="/$locale/news" params={{ locale }} icon={<Newspaper />} label={t("news")} />
            <NavLink navKey="shorts" registerRef={registerPrimaryNavRef} to="/$locale/shorts" params={{ locale }} icon={<ShieldAlert />} label={t("shorts")} />
            <NavLink navKey="trump-filings" registerRef={registerPrimaryNavRef} to="/$locale/trump-filings" params={{ locale }} icon={<FileText />} label={t("trumpFilings")} />
            <NavLink navKey="sources" registerRef={registerPrimaryNavRef} to="/$locale/sources" params={{ locale }} icon={<Database />} label={t("sources")} />
            <NavLink navKey="status" registerRef={registerPrimaryNavRef} to="/$locale/status" params={{ locale }} icon={<Globe2 />} label={t("status")} />
            <NavLink
              navKey="legal"
              registerRef={registerPrimaryNavRef}
              to="/$locale/$legalSlug"
              params={{ locale, legalSlug: "financial-disclaimer" }}
              icon={<Scale />}
              label={locale === "ko" ? "고지" : "Disclaimer"}
            />
            <Link
              to="/admin/login"
              className="focus-ring inline-flex h-11 shrink-0 items-center gap-2 rounded-md px-3 text-muted hover:bg-panelAlt hover:text-ink"
            >
              <Lock className="h-4 w-4" />
              {t("admin")}
            </Link>
            <a
              href={alternatePath}
              className="focus-ring inline-flex h-11 shrink-0 items-center rounded-md border border-line bg-panelAlt px-3 font-semibold text-ink hover:border-accent hover:bg-accentSoft"
            >
              {other.toUpperCase()}
            </a>
          </nav>
        </div>
        <div
          className="scroll-fade-x mx-auto flex max-w-7xl min-w-0 gap-3 overflow-x-auto px-3 pb-2 text-xs [contain:paint] sm:px-4 md:pb-3 lg:px-6"
          data-allow-horizontal-scroll
          aria-label={locale === "ko" ? "시장 범위 탐색" : "Market coverage navigation"}
        >
          <span className="inline-flex min-h-11 shrink-0 items-center whitespace-nowrap font-semibold text-muted">
            {t("sectors")}
          </span>
          {sectorLinks.map(([key, labelEn, labelKo]) => (
            <Link
              key={key}
              to="/$locale/sectors/$sectorKey"
              params={{ locale, sectorKey: key }}
              className="focus-ring inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center whitespace-nowrap rounded-md px-2 hover:text-accent"
            >
              {locale === "ko" ? labelKo : labelEn}
            </Link>
          ))}
          <span className="ml-2 inline-flex min-h-11 shrink-0 items-center whitespace-nowrap font-semibold text-muted">
            {t("countries")}
          </span>
          {countryLinks.map(([key, labelEn, labelKo]) => {
            const route = key === "EUROZONE" ? "/$locale/regions/$objectKey" : "/$locale/countries/$objectKey";
            return (
              <Link
                key={key}
                to={route}
                params={{ locale: asLocale(locale), objectKey: key }}
                className="focus-ring inline-flex min-h-11 min-w-11 shrink-0 items-center justify-center whitespace-nowrap rounded-md px-2 hover:text-accent"
              >
                {locale === "ko" ? labelKo : labelEn}
              </Link>
            );
          })}
        </div>
      </header>
      <main className="mx-auto max-w-7xl min-w-0 px-3 py-4 sm:px-4 sm:py-6 lg:px-6">{children}</main>
      <footer className="border-t border-line bg-panel">
        <div className="mx-auto grid max-w-7xl gap-4 px-4 py-6 text-sm text-muted md:grid-cols-4 lg:px-6">
          <Link to="/$locale/$legalSlug" params={{ locale, legalSlug: "terms" }} className="focus-ring inline-flex min-h-11 items-center rounded-md hover:text-accent">
            {t("legal.terms")}
          </Link>
          <Link to="/$locale/$legalSlug" params={{ locale, legalSlug: "privacy" }} className="focus-ring inline-flex min-h-11 items-center rounded-md hover:text-accent">
            {t("legal.privacy")}
          </Link>
          <Link to="/$locale/$legalSlug" params={{ locale, legalSlug: "source-policy" }} className="focus-ring inline-flex min-h-11 items-center rounded-md hover:text-accent">
            {t("legal.source-policy")}
          </Link>
          <Link to="/$locale/$legalSlug" params={{ locale, legalSlug: "contact" }} className="focus-ring inline-flex min-h-11 items-center rounded-md hover:text-accent">
            {t("legal.contact")}
          </Link>
        </div>
      </footer>
    </div>
  );
}

function NavLink({
  to,
  params,
  icon,
  label,
  navKey,
  registerRef
}: {
  to: string;
  params: Record<string, string>;
  icon: React.ReactElement;
  label: string;
  navKey?: string;
  registerRef?: (key: string, element: HTMLAnchorElement | null) => void;
}) {
  return (
    <Link
      ref={(element) => {
        if (navKey && registerRef) registerRef(navKey, element);
      }}
      to={to as never}
      params={params as never}
      className="focus-ring inline-flex h-11 min-w-11 shrink-0 items-center justify-center gap-2 rounded-md px-3 text-muted hover:bg-panelAlt hover:text-ink [&.active]:bg-accentSoft [&.active]:font-semibold [&.active]:text-accent"
    >
      {icon}
      {label}
    </Link>
  );
}

function getActivePrimaryNavKey(pathname: string) {
  const path = pathname.replace(/^\/(en|ko)(?=\/|$)/, "") || "/";
  if (path === "/" || path === "") return "dashboard";
  if (path.startsWith("/map")) return "map";
  if (path.startsWith("/calendar") || path.startsWith("/central-banks")) return "calendar";
  if (path.startsWith("/market-pulse")) return "market-pulse";
  if (path.startsWith("/portfolio")) return "portfolio";
  if (path.startsWith("/tickers")) return "tickers";
  if (path.startsWith("/news")) return "news";
  if (path.startsWith("/shorts")) return "shorts";
  if (path.startsWith("/trump-filings")) return "trump-filings";
  if (path.startsWith("/sources")) return "sources";
  if (path.startsWith("/status")) return "status";
  if (
    path.startsWith("/financial-disclaimer") ||
    path.startsWith("/terms") ||
    path.startsWith("/privacy") ||
    path.startsWith("/source-policy") ||
    path.startsWith("/contact") ||
    path.startsWith("/corrections")
  ) {
    return "legal";
  }
  return null;
}
