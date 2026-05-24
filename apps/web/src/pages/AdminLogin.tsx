import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";
import { KeyRound } from "lucide-react";
import { apiPost, type AdminSessionResponse } from "../lib/api";

export function AdminLogin() {
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [totpCode, setTotpCode] = useState("");
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
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

  return (
    <main className="grid min-h-screen place-items-center bg-paper px-4 text-ink">
      <form className="panel w-full max-w-md p-6" onSubmit={submit}>
        <div className="grid h-12 w-12 place-items-center rounded-md bg-accent text-paper">
          <KeyRound className="h-6 w-6" />
        </div>
        <h1 className="mt-4 text-2xl font-bold">Admin Login</h1>
        <p className="mt-2 text-sm text-muted">Owner/admin roles require TOTP after password verification.</p>
        <label className="mt-5 block text-sm font-semibold">
          Email
          <input
            className="input-control mt-2 h-11 w-full"
            autoComplete="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
        </label>
        <label className="mt-4 block text-sm font-semibold">
          Password
          <input
            className="input-control mt-2 h-11 w-full"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
        </label>
        <label className="mt-4 block text-sm font-semibold">
          TOTP
          <input
            className="input-control mt-2 h-11 w-full"
            inputMode="numeric"
            value={totpCode}
            onChange={(event) => setTotpCode(event.target.value)}
          />
        </label>
        {message ? <div className="signal-warning mt-4 p-3 text-sm">{message}</div> : null}
        <button
          className="primary-action mt-5 h-11 w-full py-0"
          disabled={busy}
        >
          {busy ? "Checking..." : "Login"}
        </button>
      </form>
    </main>
  );
}
