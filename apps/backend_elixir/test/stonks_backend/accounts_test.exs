defmodule StonksBackend.AccountsTest do
  use ExUnit.Case, async: false
  import Plug.Test

  alias StonksBackend.Accounts
  alias StonksBackend.Accounts.Crypto

  setup do
    original = Application.get_env(:stonks_backend, :settings)

    on_exit(fn ->
      if is_nil(original) do
        Application.delete_env(:stonks_backend, :settings)
      else
        Application.put_env(:stonks_backend, :settings, original)
      end
    end)
  end

  test "create_session sets 12-hour session cookie and optional short-lived CSRF cookie" do
    Application.put_env(:stonks_backend, :settings, app_env: "prod")

    {conn, csrf_token} =
      :post
      |> conn("/api/auth/login")
      |> Accounts.create_session("user-id", "admin", expose_csrf_cookie: true, persist: false)

    assert byte_size(csrf_token) > 20

    session_cookie = conn.resp_cookies[Accounts.session_cookie()]
    assert session_cookie.value
    assert session_cookie.http_only
    assert session_cookie.secure
    assert session_cookie.same_site == "Lax"
    assert session_cookie.max_age == Accounts.session_max_age()
    assert session_cookie.path == "/"

    csrf_cookie = conn.resp_cookies[Accounts.csrf_cookie()]
    assert csrf_cookie.value == csrf_token
    refute csrf_cookie.http_only
    assert csrf_cookie.secure
    assert csrf_cookie.same_site == "Lax"
    assert csrf_cookie.max_age == 5 * 60
    assert csrf_cookie.path == "/"
  end

  test "create_session omits CSRF cookie for password login by default" do
    {conn, csrf_token} =
      :post
      |> conn("/api/auth/login")
      |> Accounts.create_session("user-id", "admin", persist: false)

    assert byte_size(csrf_token) > 20
    assert conn.resp_cookies[Accounts.session_cookie()]
    refute Map.has_key?(conn.resp_cookies, Accounts.csrf_cookie())
  end

  test "create_session does not mint cookies when session persistence fails" do
    conn = conn(:post, "/api/auth/login")

    assert Accounts.create_session(conn, "user-id", "admin") == {:error, :session_unavailable}
    assert conn.resp_cookies == %{}
  end

  test "clear_session clears auth cookies on logout" do
    conn =
      :post
      |> conn("/api/auth/logout")
      |> Accounts.clear_session()

    assert conn.resp_cookies[Accounts.session_cookie()].max_age == 0
    assert conn.resp_cookies[Accounts.session_cookie()].path == "/"
    assert conn.resp_cookies[Accounts.csrf_cookie()].max_age == 0
    assert conn.resp_cookies[Accounts.csrf_cookie()].path == "/"
  end

  test "CSRF helper compares hashed tokens defensively" do
    csrf_hash = Crypto.hash_secret("csrf-token")

    assert Accounts.valid_csrf_token?("csrf-token", csrf_hash)
    refute Accounts.valid_csrf_token?("other-token", csrf_hash)
    refute Accounts.valid_csrf_token?(nil, csrf_hash)
    refute Accounts.valid_csrf_token?("csrf-token", nil)
    refute Accounts.valid_csrf_token?(String.duplicate("a", 129), csrf_hash)
    refute Accounts.valid_csrf_token?("csrf-token", String.duplicate("z", 64))
  end

  test "bootstrap_admin_config is explicit and DB-free" do
    Application.put_env(:stonks_backend, :settings,
      admin_email: " Owner@Example.COM ",
      admin_bootstrap_password: "bootstrap-password",
      admin_totp_secret: "JBSWY3DPEHPK3PXP"
    )

    assert {:ok, config} = Accounts.bootstrap_admin_config()
    assert config.email == "owner@example.com"
    assert config.password == "bootstrap-password"
    assert config.totp_secret == "JBSWY3DPEHPK3PXP"

    Application.put_env(:stonks_backend, :settings,
      admin_bootstrap_password: "bootstrap-password"
    )

    assert Accounts.bootstrap_admin_config() == {:error, :missing_bootstrap_credentials}
  end

  test "google admin allowlist normalizes explicit emails and domains" do
    Application.put_env(:stonks_backend, :settings,
      admin_email: "owner@example.com",
      google_oauth_allowed_emails: " Analyst@Example.com ",
      google_oauth_allowed_domains: " @trusted.example "
    )

    assert Accounts.google_allowed?("OWNER@example.com")
    assert Accounts.google_allowed?("analyst@example.com")
    assert Accounts.google_allowed?("person@trusted.example")
    refute Accounts.google_allowed?("trusted.example")
    refute Accounts.google_allowed?("person@other.example")
  end

  test "safe_admin_redirect_path only allows the admin root and descendants" do
    assert Accounts.safe_admin_redirect_path("/admin") == "/admin"
    assert Accounts.safe_admin_redirect_path("/admin/sources") == "/admin/sources"
    assert Accounts.safe_admin_redirect_path("/administrator") == "/admin"
    assert Accounts.safe_admin_redirect_path("//example.com/admin") == "/admin"
    assert Accounts.safe_admin_redirect_path("https://evil.example/admin") == "/admin"

    long_path = "/admin/" <> String.duplicate("a", 300)
    assert String.length(Accounts.safe_admin_redirect_path(long_path)) == 256
  end
end
