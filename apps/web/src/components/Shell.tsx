import { Link, useRouterState } from "@tanstack/react-router";
import { Activity, Calculator, Database, Globe2, LayoutDashboard, Lock, Map, Scale, SearchCheck } from "lucide-react";
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

  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="sticky top-0 z-20 overflow-x-hidden border-b border-line bg-panel/95 shadow-insetLine backdrop-blur [contain:paint]">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-4 px-4 py-4 lg:px-6">
          <Link to="/$locale" params={{ locale }} className="focus-ring flex min-h-11 items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-md bg-accent text-paper shadow-insetLine">
              <SearchCheck className="h-5 w-5" />
            </div>
            <div>
              <div className="text-base font-bold">{t("appName")}</div>
              <div className="text-xs text-muted">{t("noAdvice")}</div>
            </div>
          </Link>
          <nav className="-mx-1 flex min-w-0 basis-full items-center gap-1 overflow-x-auto px-1 pb-1 text-sm [contain:paint] [scrollbar-width:thin] md:basis-auto md:flex-wrap md:overflow-visible md:pb-0">
            <NavLink to="/$locale" params={{ locale }} icon={<LayoutDashboard />} label={t("dashboard")} />
            <NavLink to="/$locale/map" params={{ locale }} icon={<Map />} label={t("map")} />
            <NavLink to="/$locale/calendar" params={{ locale }} icon={<Activity />} label={t("calendar")} />
            <NavLink to="/$locale/portfolio" params={{ locale }} icon={<Calculator />} label={t("portfolio")} />
            <NavLink to="/$locale/sources" params={{ locale }} icon={<Database />} label={t("sources")} />
            <NavLink to="/$locale/status" params={{ locale }} icon={<Globe2 />} label={t("status")} />
            <NavLink
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
        <div className="mx-auto flex max-w-7xl min-w-0 gap-3 overflow-x-auto px-4 pb-3 text-xs [contain:paint] [scrollbar-width:thin] lg:px-6">
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
      <main className="mx-auto max-w-7xl px-4 py-6 lg:px-6">{children}</main>
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
  label
}: {
  to: string;
  params: Record<string, string>;
  icon: React.ReactElement;
  label: string;
}) {
  return (
    <Link
      to={to as never}
      params={params as never}
      className="focus-ring inline-flex h-11 shrink-0 items-center gap-2 rounded-md px-3 text-muted hover:bg-panelAlt hover:text-ink [&.active]:bg-accentSoft [&.active]:font-semibold [&.active]:text-accent"
    >
      {icon}
      {label}
    </Link>
  );
}
