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
const CentralBanksPage = lazyRoute(async () => {
  const module = await import("./pages/CalendarPage");
  return { default: () => <module.CalendarPage centralBanksOnly /> };
});
const PortfolioLabPage = lazyRoute(() => import("./pages/PortfolioLabPage"), "PortfolioLabPage");
const TickerDetailPage = lazyRoute(() => import("./pages/TickerDetailPage"), "TickerDetailPage");
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

const tickerDetailRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "tickers/$symbol",
  component: TickerDetailPage
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
    centralBanksRoute,
    portfolioRoute,
    tickerDetailRoute,
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
  adminRoute
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
    <main className="grid min-h-screen place-items-center bg-paper text-sm font-semibold text-muted">
      Loading
    </main>
  );
}
