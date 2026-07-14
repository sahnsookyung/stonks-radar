import { Link, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  BriefcaseBusiness,
  Calculator,
  LayoutDashboard,
  LineChart,
  Map,
  Menu,
  Newspaper,
  Scale,
  SearchCheck,
  ShieldAlert,
  TrendingUp,
  X
} from "lucide-react";
import { useEffect, useRef, useState, type ReactElement } from "react";
import { useTranslation } from "react-i18next";
import { alternateLocale, asLocale, useLocale } from "../lib/locale";
import { navVisibleRegions } from "../lib/watchedRegions";
import { SnapshotIncidentBanner } from "./SnapshotIncidentBanner";

const sectorLinks = [
  ["space", "Space", "우주"],
  ["drones", "Drones", "드론"],
  ["quantum", "Quantum", "양자"],
  ["semiconductors", "Semiconductors", "반도체"],
  ["oil-energy", "Oil/Energy", "석유/에너지"],
  ["big-tech", "Big Tech", "빅테크"]
];

type NavigationItem = {
  key: string;
  to: string;
  params: Record<string, string>;
  icon: ReactElement;
  label: string;
};

export function Shell({ children }: Readonly<{ children: React.ReactNode }>) {
  const locale = useLocale();
  const { t } = useTranslation();
  const coverageLinks = navVisibleRegions();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const other = alternateLocale(locale);
  const alternatePath = pathname.replace(/^\/(en|ko)(?=\/|$)/, `/${other}`);
  const activePrimaryNavKey = getActivePrimaryNavKey(pathname);
  const [menuOpen, setMenuOpen] = useState(false);
  const desktopMenuButtonRef = useRef<HTMLButtonElement>(null);
  const mobileMenuButtonRef = useRef<HTMLButtonElement>(null);
  const menuPanelRef = useRef<HTMLDivElement>(null);
  const compact = {
    pulse: locale === "ko" ? "펄스" : "Pulse",
    curves: locale === "ko" ? "금리곡선" : "Curves",
    portfolio: locale === "ko" ? "포트폴리오" : "Portfolio",
    funds: locale === "ko" ? "펀드" : "Funds",
    legal: locale === "ko" ? "고지" : "Legal"
  };
  const primaryItems: NavigationItem[] = [
    { key: "dashboard", to: "/$locale", params: { locale }, icon: <LayoutDashboard />, label: t("dashboard") },
    { key: "map", to: "/$locale/map", params: { locale }, icon: <Map />, label: t("map") },
    { key: "news", to: "/$locale/news", params: { locale }, icon: <Newspaper />, label: t("news") },
    { key: "portfolio", to: "/$locale/portfolio", params: { locale }, icon: <Calculator />, label: compact.portfolio }
  ];
  const menuItems: NavigationItem[] = [
    { key: "tickers", to: "/$locale/tickers/$symbol", params: { locale, symbol: "NVDA" }, icon: <TrendingUp />, label: t("tickers") },
    { key: "calendar", to: "/$locale/calendar", params: { locale }, icon: <Activity />, label: t("calendar") },
    { key: "market-pulse", to: "/$locale/market-pulse", params: { locale }, icon: <TrendingUp />, label: compact.pulse },
    { key: "yield-curves", to: "/$locale/yield-curves", params: { locale }, icon: <LineChart />, label: compact.curves },
    { key: "shorts", to: "/$locale/shorts", params: { locale }, icon: <ShieldAlert />, label: t("shorts") },
    { key: "funds", to: "/$locale/funds", params: { locale }, icon: <BriefcaseBusiness />, label: compact.funds },
    { key: "legal", to: "/$locale/$legalSlug", params: { locale, legalSlug: "financial-disclaimer" }, icon: <Scale />, label: compact.legal }
  ];

  useEffect(() => setMenuOpen(false), [pathname]);

  useEffect(() => {
    if (!menuOpen) return undefined;
    const focusable = menuPanelRef.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled]):not([tabindex="-1"]), [tabindex]:not([tabindex="-1"])');
    focusable?.[0]?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeMenuAndRestoreFocus();
        return;
      }
      if (event.key !== "Tab" || !focusable?.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [menuOpen]);

  function closeMenuAndRestoreFocus() {
    setMenuOpen(false);
    globalThis.window.requestAnimationFrame(() => {
      const desktop = globalThis.window.matchMedia("(min-width: 1024px)").matches;
      (desktop ? desktopMenuButtonRef : mobileMenuButtonRef).current?.focus();
    });
  }

  return (
    <div className="min-h-screen bg-paper text-ink">
      <header className="sticky top-0 z-20 border-b border-line bg-panel/95 shadow-insetLine backdrop-blur">
        <div className="flex w-full items-center gap-3 px-3 py-2 sm:px-4 md:py-3 lg:px-6 2xl:px-8">
          <Link to="/$locale" params={{ locale }} activeOptions={{ exact: true }} className="focus-ring flex min-h-11 min-w-0 shrink items-center gap-2 rounded-md md:gap-3 lg:min-w-[245px]">
            <div className="grid h-9 w-9 shrink-0 place-items-center rounded-md bg-accent text-paper shadow-insetLine md:h-10 md:w-10"><SearchCheck className="h-5 w-5" /></div>
            <div className="min-w-0"><div className="truncate text-sm font-bold leading-5 sm:text-base">{t("appName")}</div><div className="sr-only text-xs text-muted xl:not-sr-only xl:block">{t("noAdvice")}</div></div>
          </Link>

          <nav className="ml-auto hidden min-w-0 items-center gap-1 text-sm lg:flex" aria-label={locale === "ko" ? "기본 탐색" : "Primary navigation"}>
            {primaryItems.map((item) => <NavLink key={item.key} item={item} active={activePrimaryNavKey === item.key} />)}
            <MenuButton ref={desktopMenuButtonRef} open={menuOpen} label={locale === "ko" ? "더보기" : "More"} onClick={() => setMenuOpen((open) => !open)} />
          </nav>
        </div>

        <nav className="grid grid-cols-5 border-t border-line px-1 py-1 lg:hidden" aria-label={locale === "ko" ? "모바일 기본 탐색" : "Mobile primary navigation"}>
          {primaryItems.map((item) => <NavLink key={item.key} item={item} active={activePrimaryNavKey === item.key} mobile />)}
          <MenuButton ref={mobileMenuButtonRef} open={menuOpen} label={locale === "ko" ? "메뉴" : "Menu"} onClick={() => setMenuOpen((open) => !open)} mobile />
        </nav>
      </header>

      {menuOpen ? (
        <NavigationMenu
          panelRef={menuPanelRef}
          locale={locale}
          alternatePath={alternatePath}
          otherLocale={other}
          activeKey={activePrimaryNavKey}
          menuItems={menuItems}
          coverageLinks={coverageLinks}
          onClose={closeMenuAndRestoreFocus}
        />
      ) : null}

      <SnapshotIncidentBanner />
      <main className="min-w-0 px-3 py-4 sm:px-4 sm:py-6 lg:px-6 2xl:px-8">{children}</main>
      <footer className="border-t border-line bg-panel">
        <div className="grid gap-4 px-4 py-6 text-sm text-muted md:grid-cols-4 lg:px-6 2xl:px-8">
          {["terms", "privacy", "source-policy", "contact"].map((legalSlug) => (
            <Link key={legalSlug} to="/$locale/$legalSlug" params={{ locale, legalSlug }} className="focus-ring inline-flex min-h-11 items-center rounded-md hover:text-accent">{t(`legal.${legalSlug}`)}</Link>
          ))}
        </div>
      </footer>
    </div>
  );
}

function NavigationMenu({
  panelRef,
  locale,
  alternatePath,
  otherLocale,
  activeKey,
  menuItems,
  coverageLinks,
  onClose
}: Readonly<{
  panelRef: React.RefObject<HTMLDivElement | null>;
  locale: "en" | "ko";
  alternatePath: string;
  otherLocale: "en" | "ko";
  activeKey: string | null;
  menuItems: NavigationItem[];
  coverageLinks: ReturnType<typeof navVisibleRegions>;
  onClose: () => void;
}>) {
  return (
    <div className="fixed inset-0 z-50">
      <button type="button" tabIndex={-1} aria-hidden="true" className="absolute inset-0 cursor-default bg-black/60 backdrop-blur-sm" onClick={onClose} />
      <div ref={panelRef} role="dialog" aria-modal="true" aria-labelledby="site-menu-heading" className="absolute inset-y-0 right-0 w-[min(92vw,430px)] overflow-y-auto border-l border-line bg-panel p-4 shadow-2xl transition-transform motion-reduce:transition-none sm:p-5">
        <div className="flex items-center justify-between gap-3">
          <div><h2 id="site-menu-heading" className="text-lg font-bold">{locale === "ko" ? "사이트 메뉴" : "Site menu"}</h2><p className="mt-1 text-xs text-muted">{locale === "ko" ? "탐색, 테마, 지역, 언어" : "Navigation, themes, regions, and language"}</p></div>
          <button type="button" className="focus-ring grid h-11 w-11 place-items-center rounded-md border border-line hover:bg-panelAlt" aria-label={locale === "ko" ? "메뉴 닫기" : "Close menu"} onClick={onClose}><X className="h-5 w-5" /></button>
        </div>

        <nav className="mt-5 grid grid-cols-2 gap-2" aria-label={locale === "ko" ? "추가 탐색" : "Additional navigation"}>
          {menuItems.map((item) => <MenuLink key={item.key} item={item} active={activeKey === item.key} onClick={onClose} />)}
          <a href={alternatePath} onClick={onClose} className="focus-ring flex min-h-12 items-center justify-center rounded-md border border-line bg-panelAlt px-3 font-semibold hover:border-accent hover:text-accent">{otherLocale.toUpperCase()}</a>
        </nav>

        <MenuSection title={locale === "ko" ? "테마" : "Themes"}>
          {sectorLinks.map(([key, labelEn, labelKo]) => (
            <Link key={key} to="/$locale/sectors/$sectorKey" params={{ locale, sectorKey: key }} onClick={onClose} className="focus-ring inline-flex min-h-11 items-center rounded-md border border-line bg-panelAlt px-3 text-sm font-semibold hover:border-accent hover:text-accent">{locale === "ko" ? labelKo : labelEn}</Link>
          ))}
        </MenuSection>

        <MenuSection title={locale === "ko" ? "지역" : "Regions"}>
          {coverageLinks.map((region) => {
            const route = region.type === "country" ? "/$locale/countries/$objectKey" : "/$locale/regions/$objectKey";
            return <Link key={region.key} to={route} params={{ locale: asLocale(locale), objectKey: region.key }} onClick={onClose} className="focus-ring inline-flex min-h-11 items-center rounded-md border border-line bg-panelAlt px-3 text-sm font-semibold hover:border-accent hover:text-accent">{region.display_names[asLocale(locale)] ?? region.display_names.en}</Link>;
          })}
        </MenuSection>
      </div>
    </div>
  );
}

function MenuSection({ title, children }: Readonly<{ title: string; children: React.ReactNode }>) {
  return <section className="mt-6 border-t border-line pt-5"><h3 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h3><div className="mt-3 flex flex-wrap gap-2">{children}</div></section>;
}

const MenuButton = function MenuButton({ open, label, onClick, mobile = false, ref }: Readonly<{ open: boolean; label: string; onClick: () => void; mobile?: boolean; ref: React.Ref<HTMLButtonElement> }>) {
  return <button ref={ref} type="button" aria-expanded={open} aria-haspopup="dialog" className={`focus-ring inline-flex min-h-11 min-w-11 items-center justify-center rounded-md font-semibold transition-colors motion-reduce:transition-none hover:bg-panelAlt hover:text-ink ${open ? "bg-accentSoft text-accent" : "text-muted"} ${mobile ? "flex-col gap-0.5 px-1 text-[10px]" : "gap-2 px-3 text-sm"}`} onClick={onClick}><Menu className="h-5 w-5" />{label}</button>;
};

function NavLink({ item, active, mobile = false }: Readonly<{ item: NavigationItem; active: boolean; mobile?: boolean }>) {
  return <Link to={item.to as never} params={item.params as never} activeOptions={{ exact: true }} aria-current={active ? "page" : undefined} className={`focus-ring inline-flex min-h-11 min-w-11 items-center justify-center rounded-md transition-colors motion-reduce:transition-none hover:bg-panelAlt hover:text-ink ${active ? "bg-accentSoft font-semibold text-accent" : "text-muted"} ${mobile ? "flex-col gap-0.5 px-1 text-[10px]" : "gap-2 px-3 text-sm"}`}>{item.icon}{item.label}</Link>;
}

function MenuLink({ item, active, onClick }: Readonly<{ item: NavigationItem; active: boolean; onClick: () => void }>) {
  return <Link to={item.to as never} params={item.params as never} aria-current={active ? "page" : undefined} onClick={onClick} className={`focus-ring flex min-h-12 items-center gap-2 rounded-md border px-3 text-sm font-semibold ${active ? "border-accent bg-accentSoft text-accent" : "border-line bg-panelAlt hover:border-accent hover:text-accent"}`}>{item.icon}{item.label}</Link>;
}

function getActivePrimaryNavKey(pathname: string) {
  const path = pathname.replace(/^\/(en|ko)(?=\/|$)/, "") || "/";
  if (path === "/" || path === "") return "dashboard";
  if (path.startsWith("/map")) return "map";
  if (path.startsWith("/calendar") || path.startsWith("/central-banks")) return "calendar";
  if (path.startsWith("/market-pulse")) return "market-pulse";
  if (path.startsWith("/yield-curves")) return "yield-curves";
  if (path.startsWith("/portfolio") || path.startsWith("/dashboard") || path.startsWith("/onboarding") || path.startsWith("/portfolios") || path.startsWith("/settings")) return "portfolio";
  if (path.startsWith("/funds") || path.startsWith("/trump-filings")) return "funds";
  if (path.startsWith("/tickers")) return "tickers";
  if (path.startsWith("/news")) return "news";
  if (path.startsWith("/shorts")) return "shorts";
  if (["/financial-disclaimer", "/terms", "/privacy", "/source-policy", "/contact", "/corrections"].some((prefix) => path.startsWith(prefix))) return "legal";
  return null;
}
