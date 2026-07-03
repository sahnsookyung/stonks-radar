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
    if (isBlockedHost(url.hostname)) return null;
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

function isBlockedHost(hostname: string): boolean {
  const hostnameValue = hostname.toLowerCase().replace(/^\[|\]$/g, "");

  if (
    hostnameValue === "localhost" ||
    hostnameValue.endsWith(".localhost") ||
    hostnameValue === "::" ||
    hostnameValue === "::1" ||
    hostnameValue.includes(":")
  ) {
    return true;
  }

  const ipv4Parts = parseIPv4(hostnameValue);
  if (!ipv4Parts) return false;

  const [first, second, third] = ipv4Parts;

  return (
    first === 0 ||
    first === 10 ||
    first === 127 ||
    first >= 224 ||
    (first === 100 && second >= 64 && second <= 127) ||
    (first === 169 && second === 254) ||
    (first === 172 && second >= 16 && second <= 31) ||
    (first === 192 && second === 0 && third === 0) ||
    (first === 192 && second === 168) ||
    (first === 198 && (second === 18 || second === 19)) ||
    (first === 198 && second === 51 && third === 100) ||
    (first === 203 && second === 0 && third === 113)
  );
}

function parseIPv4(hostname: string): [number, number, number, number] | null {
  const parts = hostname.split(".");
  if (parts.length !== 4) return null;

  const parsed = parts.map((part) => {
    if (!/^\d{1,3}$/.test(part)) return null;
    const value = Number(part);
    return value >= 0 && value <= 255 ? value : null;
  });

  return parsed.every((part): part is number => part !== null)
    ? ([parsed[0], parsed[1], parsed[2], parsed[3]] as [number, number, number, number])
    : null;
}
