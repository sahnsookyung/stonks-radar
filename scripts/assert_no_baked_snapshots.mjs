import { readdir } from "node:fs/promises";
import path from "node:path";

const snapshotRoot = path.resolve("apps/web/public/public");

async function jsonFiles(root) {
  let entries;

  try {
    entries = await readdir(root, { withFileTypes: true });
  } catch (error) {
    if (error?.code === "ENOENT") return [];
    throw error;
  }

  const nested = await Promise.all(
    entries.map((entry) => {
      const entryPath = path.join(root, entry.name);
      return entry.isDirectory() ? jsonFiles(entryPath) : [entryPath];
    }),
  );

  return nested.flat().filter((entryPath) => entryPath.endsWith(".json"));
}

const bakedSnapshots = await jsonFiles(snapshotRoot);

if (bakedSnapshots.length > 0) {
  throw new Error(
    `Baked snapshot data is prohibited; publish through the shared runtime volume instead:\n${bakedSnapshots.join("\n")}`,
  );
}

console.log("No baked public snapshot data found; runtime publication is required.");
