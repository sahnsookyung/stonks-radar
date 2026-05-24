import {
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  redirect
} from "@tanstack/react-router";
import { Shell } from "./components/Shell";
import { AdminDashboard } from "./pages/AdminDashboard";
import { AdminLogin } from "./pages/AdminLogin";
import { CalendarPage } from "./pages/CalendarPage";
import { CountryRegionPage } from "./pages/CountryRegionPage";
import { HomePage } from "./pages/HomePage";
import { LegalPage } from "./pages/LegalPage";
import { MapPage } from "./pages/MapPage";
import { MethodologyPage } from "./pages/MethodologyPage";
import { PortfolioLabPage } from "./pages/PortfolioLabPage";
import { ScenarioBasketPage } from "./pages/ScenarioBasketPage";
import { SectorPage } from "./pages/SectorPage";
import { SourcesPage } from "./pages/SourcesPage";
import { SourceStatusPage } from "./pages/SourceStatusPage";

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

const centralBanksRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "central-banks",
  component: () => <CalendarPage centralBanksOnly />
});

const portfolioRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "portfolio",
  component: PortfolioLabPage
});

const sourcesRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "sources",
  component: SourcesPage
});

const countryRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "countries/$objectKey",
  component: () => <CountryRegionPage type="country" />
});

const regionRoute = createRoute({
  getParentRoute: () => localeRoute,
  path: "regions/$objectKey",
  component: () => <CountryRegionPage type="region" />
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
    centralBanksRoute,
    portfolioRoute,
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
