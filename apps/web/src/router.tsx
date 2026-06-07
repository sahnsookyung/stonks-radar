import { Suspense, lazy, type ComponentType, type ReactElement } from "react";
import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  redirect
} from "@tanstack/react-router";
import { Shell } from "./components/Shell";
import { HomePage } from "./pages/HomePage";
import { MapPage } from "./pages/MapPage";

const CalendarPage = lazyRoute(() => import("./pages/CalendarPage"), "CalendarPage");
const MarketPulsePage = lazyRoute(() => import("./pages/MarketPulsePage"), "MarketPulsePage");
const YieldCurvesPage = lazyRoute(() => import("./pages/YieldCurvesPage"), "YieldCurvesPage");
const CentralBanksPage = lazyRoute(async () => {
  const module = await import("./pages/CalendarPage");
  return { default: () => <module.CalendarPage centralBanksOnly /> };
});
const PortfolioLabPage = lazyRoute(() => import("./pages/PortfolioLabPage"), "PortfolioLabPage");
const FundsTrackerPage = lazyRoute(() => import("./pages/FundsTrackerPage"), "FundsTrackerPage");
const FundPortfolioPage = lazyRoute(() => import("./pages/FundPortfolioPage"), "FundPortfolioPage");
const TickerDetailPage = lazyRoute(() => import("./pages/TickerDetailPage"), "TickerDetailPage");
const EntityPage = lazyRoute(() => import("./pages/EntityPage"), "EntityPage");
const NewsPage = lazyRoute(() => import("./pages/NewsPage"), "NewsPage");
const NewsEventPage = lazyRoute(() => import("./pages/NewsEventPage"), "NewsEventPage");
const ShortsPage = lazyRoute(() => import("./pages/ShortsPage"), "ShortsPage");
const TrumpFilingsPage = lazyRoute(() => import("./pages/TrumpFilingsPage"), "TrumpFilingsPage");
const SourcesPage = lazyRoute(() => import("./pages/SourcesPage"), "SourcesPage");
const CountryPage = lazyRoute(async () => {
  const module = await import("./pages/CountryRegionPage");
  return { default: () => <module.CountryRegionPage type="country" /> };
});
const RegionPage = lazyRoute(async () => {
  const module = await import("./pages/CountryRegionPage");
  return { default: () => <module.CountryRegionPage type="region" /> };
});
const SectorPage = lazyRoute(() => import("./pages/SectorPage"), "SectorPage");
const ScenarioBasketPage = lazyRoute(() => import("./pages/ScenarioBasketPage"), "ScenarioBasketPage");
const MethodologyPage = lazyRoute(() => import("./pages/MethodologyPage"), "MethodologyPage");
const SourceStatusPage = lazyRoute(() => import("./pages/SourceStatusPage"), "SourceStatusPage");
const LegalPage = lazyRoute(() => import("./pages/LegalPage"), "LegalPage");
const AdminLogin = lazyRoute(() => import("./pages/AdminLogin"), "AdminLogin");
const AdminDashboard = lazyRoute(() => import("./pages/AdminDashboard"), "AdminDashboard");

const rootRoute = createRootRoute({
  component: () => <Outlet />
});

const localeRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "$locale",
  beforeLoad: ({ params }) => {
    if (params.locale !== "en" && params.locale !== "ko") {
      throw redirect({ to: "/$locale", params: { locale: "en" } });
    }
  },
  component: () => (
    <Shell>
      <Outlet />
    </Shell>
  )
});

const homeRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "/",
  component: HomePage
});

const mapRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "map",
  component: MapPage
});

const calendarRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "calendar",
  component: CalendarPage
});

const marketPulseRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "market-pulse",
  component: MarketPulsePage
});

const yieldCurvesRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "yield-curves",
  component: YieldCurvesPage
});

const centralBanksRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "central-banks",
  component: CentralBanksPage
});

const portfolioRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolio",
  component: PortfolioLabPage
});

const portfolioGlossaryRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolio/glossary",
  component: PortfolioLabPage
});

const portfolioOnboardingRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "onboarding",
  component: PortfolioLabPage
});

const portfolioDashboardRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "dashboard",
  component: PortfolioLabPage
});

const portfoliosRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios",
  component: PortfolioLabPage
});

const portfolioOverviewRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId",
  component: PortfolioLabPage
});

const portfolioXrayRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/xray",
  component: PortfolioLabPage
});

const portfolioAtlasRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/atlas",
  component: PortfolioLabPage
});

const portfolioBuilderRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/builder",
  component: PortfolioLabPage
});

const portfolioBacktestRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/backtest",
  component: PortfolioLabPage
});

const portfolioMonteCarloRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/monte-carlo",
  component: PortfolioLabPage
});

const portfolioRebalanceRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/rebalance",
  component: PortfolioLabPage
});

const portfolioFeesRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/fees",
  component: PortfolioLabPage
});

const portfolioTaxLotsRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/tax-lots",
  component: PortfolioLabPage
});

const portfolioHoldingsRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/holdings",
  component: PortfolioLabPage
});

const portfolioTransactionsRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolios/$portfolioId/transactions",
  component: PortfolioLabPage
});

const settingsRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "settings",
  component: PortfolioLabPage
});

const settingsProfileRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "settings/profile",
  component: PortfolioLabPage
});

const settingsAssumptionsRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "settings/assumptions",
  component: PortfolioLabPage
});

const settingsDataSourcesRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "settings/data-sources",
  component: PortfolioLabPage
});

const settingsSecurityRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "settings/security",
  component: PortfolioLabPage
});

const fundsTrackerRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "funds",
  component: FundsTrackerPage
});

const fundPortfolioRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "funds/$fundKey",
  component: FundPortfolioPage
});

const tickerDetailRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "tickers/$symbol",
  component: TickerDetailPage
});

const entityRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "entities/$routeKey",
  component: EntityPage
});

const newsRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "news",
  component: NewsPage
});

const newsEventRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "news/events/$eventId",
  component: NewsEventPage
});

const shortsRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "shorts",
  component: ShortsPage
});

const trumpFilingsRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "trump-filings",
  component: TrumpFilingsPage
});

const sourcesRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "sources",
  component: SourcesPage
});

const countryRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "countries/$objectKey",
  component: CountryPage
});

const regionRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "regions/$objectKey",
  component: RegionPage
});

const sectorRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "sectors/$sectorKey",
  component: SectorPage
});

const scenarioRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "scenario-baskets/$basketKey",
  component: ScenarioBasketPage
});

const methodologyRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "methodology",
  component: MethodologyPage
});

const statusRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "status",
  component: SourceStatusPage
});

const legalRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "$legalSlug",
  component: LegalPage
});

const adminLoginRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/login",
  component: AdminLogin
});

const adminRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin",
  component: AdminDashboard
});

const adminFeatureGatesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/feature-gates",
  component: AdminDashboard
});

const adminUsersRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/users",
  component: AdminDashboard
});

const adminUsageRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/usage",
  component: AdminDashboard
});

const adminJobsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/jobs",
  component: AdminDashboard
});

const adminQueuesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/queues",
  component: AdminDashboard
});

const adminDataSourcesRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/data-sources",
  component: AdminDashboard
});

const adminInstrumentsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/instruments",
  component: AdminDashboard
});

const adminSystemConfigRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "admin/system-config",
  component: AdminDashboard
});

const indexRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/",
  beforeLoad: () => {
    throw redirect({ to: "/$locale", params: { locale: "en" } });
  }
});

const routeTree = rootRoute.addChildren([
  indexRoute,
  localeRoute.addChildren([
    homeRoute,
    mapRoute,
    calendarRoute,
    marketPulseRoute,
    yieldCurvesRoute,
    centralBanksRoute,
    portfolioRoute,
    portfolioGlossaryRoute,
    portfolioOnboardingRoute,
    portfolioDashboardRoute,
    portfoliosRoute,
    portfolioOverviewRoute,
    portfolioXrayRoute,
    portfolioAtlasRoute,
    portfolioBuilderRoute,
    portfolioBacktestRoute,
    portfolioMonteCarloRoute,
    portfolioRebalanceRoute,
    portfolioFeesRoute,
    portfolioTaxLotsRoute,
    portfolioHoldingsRoute,
    portfolioTransactionsRoute,
    settingsRoute,
    settingsProfileRoute,
    settingsAssumptionsRoute,
    settingsDataSourcesRoute,
    settingsSecurityRoute,
    fundsTrackerRoute,
    fundPortfolioRoute,
    tickerDetailRoute,
    entityRoute,
    newsRoute,
    newsEventRoute,
    shortsRoute,
    trumpFilingsRoute,
    sourcesRoute,
    countryRoute,
    regionRoute,
    sectorRoute,
    scenarioRoute,
    methodologyRoute,
    statusRoute,
    legalRoute
  ]),
  adminLoginRoute,
  adminRoute,
  adminFeatureGatesRoute,
  adminUsersRoute,
  adminUsageRoute,
  adminJobsRoute,
  adminQueuesRoute,
  adminDataSourcesRoute,
  adminInstrumentsRoute,
  adminSystemConfigRoute
]);

export const router = createRouter({ routeTree });

declare module "@tanstack/react-router" {
  interface Register {
    router: typeof router;
  }
}

type LazyRouteComponent = () => ReactElement;

function lazyRoute<T extends Record<string, ComponentType>>(
  loader: () => Promise<T>,
  exportName: keyof T
): LazyRouteComponent;
function lazyRoute(loader: () => Promise<{ default: ComponentType }>): LazyRouteComponent;
function lazyRoute<T extends Record<string, ComponentType>>(
  loader: () => Promise<T> | Promise<{ default: ComponentType }>,
  exportName?: keyof T
) {
  const Component = lazy(async () => {
    const module = await loader();
    return { default: exportName ? (module as T)[exportName] : (module as { default: ComponentType }).default };
  });
  return function RouteComponent() {
    return (
      <Suspense fallback={<RouteFallback />}>
        <Component />
      </Suspense>
    );
  };
}

function RouteFallback() {
  return (
    <div className="grid min-h-[70vh] place-items-center bg-paper text-sm font-semibold text-muted" role="status" aria-live="polite">
      Loading
    </div>
  );
}
