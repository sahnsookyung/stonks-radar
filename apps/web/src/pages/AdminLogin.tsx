import { useEffect, useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { KeyRound, ShieldCheck } from "lucide-react";
import {
  apiGet,
  apiPost,
  syncCsrfTokenFromCookie,
  type AdminSessionResponse,
  type GoogleAdminAuthConfig
} from "../lib/api";

export function AdminLogin() {
  const navigate = useNavigate();
  const [googleConfig, setGoogleConfig] = useState<GoogleAdminAuthConfig | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    syncCsrfTokenFromCookie();
    const params = new URLSearchParams(globalThis.window.location.search);
    const oauthError = params.get("oauth_error");
    if (oauthError) {
      setMessage(`Google sign-in did not complete: ${oauthError}`);
    }
    apiGet<GoogleAdminAuthConfig>("/api/auth/google/config")
      .then(setGoogleConfig)
      .catch(() => setGoogleConfig({ enabled: false, recommended: false, start_url: null, fallback_password_login: true, private_yahoo_admin_eligible: false, allowed_hint: null }));
  }, []);

  async function submit(event: { preventDefault(): void }) {
    event.preventDefault();
    setBusy(true);
    setMessage(null);
    try {
      const response = await apiPost<AdminSessionResponse>("/api/auth/login", {
        email,
        password,
        totp_code: totpCode || null
      });
      if (response.status === "totp_required") {
        setMessage(response.message ?? "TOTP is required.");
        return;
      }
      if (response.csrf_token) {
        sessionStorage.setItem("frw_csrf", response.csrf_token);
      }
      await navigate({ to: "/admin" });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Login failed");
    } finally {
      setBusy(false);
    }
  }

  function startGoogleLogin() {
    const startUrl = googleConfig?.start_url;
    if (!startUrl) {
      setMessage("Google admin sign-in is not configured.");
      return;
    }
    globalThis.window.location.href = `${startUrl}?redirect_to=${encodeURIComponent("/admin")}`;
  }

  return (
    <main className="grid min-h-screen place-items-center bg-paper px-4 text-ink">
      <form className="panel w-full max-w-lg p-6" onSubmit={submit}>
        <div className="grid h-12 w-12 place-items-center rounded-md bg-accent text-paper">
          <KeyRound className="h-6 w-6" />
        </div>
        <h1 className="mt-4 text-2xl font-bold">Admin Login</h1>
        <p className="mt-2 text-sm text-muted">
          Google admin sign-in is the preferred path for private Yahoo-backed portfolio analysis. Password and TOTP remain as a break-glass fallback.
        </p>
        <section className="mt-5 rounded-md border border-line bg-paper-soft p-4">
          <div className="flex items-start gap-3">
            <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md bg-accent/15 text-accent">
              <ShieldCheck className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <h2 className="text-base font-bold">Google admin sign-in</h2>
              <p className="mt-1 text-sm text-muted">
                {googleConfig?.enabled
                  ? `Allowed accounts: ${googleConfig.allowed_hint ?? "configured admin allowlist"}.`
                  : "Not configured yet. Add Google OAuth credentials to enable this path."}
              </p>
              <p className="mt-1 text-sm text-muted">
                Private Yahoo data remains admin-only and is never promoted into public snapshots.
              </p>
            </div>
          </div>
          <button
            type="button"
            className="primary-action mt-4 h-11 w-full py-0"
            disabled={!googleConfig?.enabled}
            onClick={startGoogleLogin}
          >
            Continue with Google
          </button>
        </section>
        <details className="mt-5 rounded-md border border-line p-4" open={!googleConfig?.enabled}>
          <summary className="cursor-pointer text-sm font-bold text-muted">Password / TOTP fallback</summary>
          <label className="mt-5 block text-sm font-semibold">
            <span>Email</span>
            <input
              className="input-control mt-2 h-11 w-full"
              autoComplete="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
            />
          </label>
          <label className="mt-4 block text-sm font-semibold">
            <span>Password</span>
            <input
              className="input-control mt-2 h-11 w-full"
              type="password"
              autoComplete="current-password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </label>
          <label className="mt-4 block text-sm font-semibold">
            <span>TOTP</span>
            <input
              className="input-control mt-2 h-11 w-full"
              inputMode="numeric"
              value={totpCode}
              onChange={(event) => setTotpCode(event.target.value)}
            />
          </label>
          <button
            className="secondary-action mt-5 h-11 w-full py-0"
            disabled={busy}
          >
            {busy ? "Checking..." : "Login with password"}
          </button>
        </details>
        {message ? <div className="signal-warning mt-4 p-3 text-sm">{message}</div> : null}
      </form>
    </main>
  );
}
