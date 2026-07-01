import watchedRegions from "../../../../packages/shared-config/watched-regions.json";
import type { Locale, WatchedRegionCoverage } from "@frw/shared-types";

export type WatchedRegionConfig = {
  key: string;
  type: "country" | "region" | "chokepoint";
  iso3: string | null;
  display_names: Record<Locale, string>;
  natural_earth_names: string[];
  gdelt_terms: string[];
  groups: string[];
  priority: number;
  gdp_rank: number | null;
  gather_news: boolean;
  render_on_map: boolean;
  nav_visible: boolean;
  coverage_window_days: number;
};

export const WATCHED_REGION_CONFIG_VERSION = watchedRegions.version;
export const WATCHED_REGIONS = watchedRegions.regions as WatchedRegionConfig[];

export function navVisibleRegions() {
  return WATCHED_REGIONS.filter((region) => region.nav_visible);
}

export function naturalEarthNamesForCoverage(regions: WatchedRegionCoverage[] | undefined) {
  const configuredByKey = new Map(WATCHED_REGIONS.map((region) => [region.key, region]));
  return (regions ?? [])
    .filter((region) => region.render_on_map)
    .flatMap((region) => {
      const configured = configuredByKey.get(region.key);
      const names = region.natural_earth_names?.length
        ? region.natural_earth_names
        : configured?.natural_earth_names ?? [];
      return names;
    })
    .filter((name, index, names) => name && names.indexOf(name) === index);
}
