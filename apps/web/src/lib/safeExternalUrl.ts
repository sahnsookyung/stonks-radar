const SCHEME_RE = /^[a-z][a-z\d+.-]*:/i;
const HOSTLIKE_RE = /^[a-z\d.-]+\.[a-z]{2,}(?::\d+)?(?:[/?#].*)?$/i;

export function safeExternalUrl(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  if (!trimmed) return null;

  const candidate = normalizeExternalUrl(trimmed);
  if (!candidate) return null;

  try {
    const url = new URL(candidate);
    if (!["https:", "http:"].includes(url.protocol)) return null;
    if (url.username || url.password) return null;
    return url.href;
  } catch {
    return null;
  }
}

function normalizeExternalUrl(value: string): string | null {
  if (SCHEME_RE.test(value)) return value;
  if (value.startsWith("//")) return `https:${value}`;
  if (HOSTLIKE_RE.test(value)) return `https://${value}`;
  return null;
}
