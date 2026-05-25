const reloadKey = "stonks-radar:missing-chunk-reload-at";

try {
  const now = Date.now();
  const lastReload = Number(sessionStorage.getItem(reloadKey) || "0");
  if (now - lastReload > 30000) {
    sessionStorage.setItem(reloadKey, String(now));
    location.reload();
  }
} catch {
  location.reload();
}

export default function MissingChunk() {
  return null;
}
