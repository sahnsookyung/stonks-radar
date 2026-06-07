export interface AdminSessionResponse {
  status: "totp_required" | "ok";
  csrf_token?: string;
  message?: string;
}

export interface GoogleAdminAuthConfig {
  enabled: boolean;
  recommended: boolean;
  start_url: string | null;
  fallback_password_login: boolean;
  private_yahoo_admin_eligible: boolean;
  allowed_hint: string | null;
}

export async function apiPost<T>(path: string, body: unknown, csrfToken?: string): Promise<T> {
  const response = await fetch(path, {
    method: "POST",
    credentials: "include",
    headers: {
      "Content-Type": "application/json",
      ...(csrfToken ? { "x-csrf-token": csrfToken } : {})
    },
    body: JSON.stringify(body)
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export async function apiGet<T>(path: string): Promise<T> {
  const response = await fetch(path, {
    credentials: "include",
    headers: {
      Accept: "application/json"
    }
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

export function syncCsrfTokenFromCookie(): string | null {
  const match = document.cookie
    .split(";")
    .map((value) => value.trim())
    .find((value) => value.startsWith("frw_csrf="));
  if (!match) {
    return sessionStorage.getItem("frw_csrf");
  }
  const token = decodeURIComponent(match.slice("frw_csrf=".length));
  if (token) {
    sessionStorage.setItem("frw_csrf", token);
    document.cookie = "frw_csrf=; Max-Age=0; path=/; SameSite=Lax";
  }
  return token || sessionStorage.getItem("frw_csrf");
}
