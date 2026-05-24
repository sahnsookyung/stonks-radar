import { readFile, writeFile, mkdir } from "node:fs/promises";
import { feature } from "topojson-client";

const root = new URL("../", import.meta.url);
const source = new URL("../node_modules/world-atlas/countries-110m.json", import.meta.url);
const target = new URL("../apps/web/public/map/natural-earth/countries-110m.geojson", import.meta.url);

const world = JSON.parse(await readFile(source, "utf8"));
const countries = feature(world, world.objects.countries);

countries.metadata = {
  source: "Natural Earth Admin 0 country boundaries via world-atlas",
  scale: "1:110m",
  license: "Public domain",
  generated_by: "scripts/build_map_assets.mjs"
};

await mkdir(new URL("./", target), { recursive: true });
await writeFile(target, JSON.stringify(countries));
console.log(`Wrote ${target.pathname.replace(root.pathname, "")}`);
