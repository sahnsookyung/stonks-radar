defmodule StonksBackendWeb.AuthControllerTest do
  use ExUnit.Case, async: false
  import Plug.Conn
  import Plug.Test

  @opts StonksBackendWeb.Router.init([])

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

  test "/api/auth/me returns legacy-compatible unauthenticated JSON" do
    conn =
      :get
      |> conn("/api/auth/me")
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 401
    assert Jason.decode!(conn.resp_body) == %{"detail" => "Not authenticated"}
  end

  test "/api/auth/logout returns legacy-compatible unauthenticated JSON" do
    conn =
      :post
      |> conn("/api/auth/logout")
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 401
    assert Jason.decode!(conn.resp_body) == %{"detail" => "Not authenticated"}
    assert conn.resp_cookies == %{}
  end

  test "google config reports disabled provider with password fallback" do
    conn =
      :get
      |> conn("/api/auth/google/config")
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 200

    assert Jason.decode!(conn.resp_body) == %{
             "allowed_hint" => "1 explicit admin email(s)",
             "enabled" => false,
             "fallback_password_login" => true,
             "private_yahoo_admin_eligible" => false,
             "recommended" => false,
             "start_url" => nil
           }
  end

  test "google config reports enabled provider and allowed hint" do
    Application.put_env(:stonks_backend, :settings,
      google_oauth_admin_enabled: "true",
      google_oauth_client_id: "client-id",
      google_oauth_client_secret: "client-secret",
      google_oauth_allowed_domains: "trusted.example",
      yahoo_admin_enabled: "true"
    )

    conn =
      :get
      |> conn("/api/auth/google/config")
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 200

    assert Jason.decode!(conn.resp_body) == %{
             "allowed_hint" => "1 explicit admin email(s)",
             "enabled" => true,
             "fallback_password_login" => true,
             "private_yahoo_admin_eligible" => true,
             "recommended" => true,
             "start_url" => "/api/auth/google/start"
           }
  end

  test "google start returns not configured status when provider env is absent" do
    conn =
      :get
      |> conn("/api/auth/google/start", %{"redirect_to" => "/admin"})
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 404
    assert conn.resp_body == "Google OAuth admin login is not configured."
  end

  test "google start redirects with state, nonce, and safe admin redirect when configured" do
    Application.put_env(:stonks_backend, :settings,
      public_base_url: "https://stonks.example",
      google_oauth_admin_enabled: "true",
      google_oauth_client_id: "client-id",
      google_oauth_client_secret: "client-secret"
    )

    conn =
      :get
      |> conn("/api/auth/google/start", %{"redirect_to" => "https://evil.example/admin"})
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 302
    location = get_resp_header(conn, "location") |> List.first()
    uri = URI.parse(location)
    params = URI.decode_query(uri.query)

    assert uri.scheme == "https"
    assert uri.host == "accounts.google.com"
    assert params["client_id"] == "client-id"
    assert params["redirect_uri"] == "https://stonks.example/api/auth/google/callback"
    assert params["response_type"] == "code"
    assert params["scope"] == "openid email profile"
    assert params["prompt"] == "select_account"
    assert params["include_granted_scopes"] == "true"
    assert byte_size(params["state"]) > 20
    assert byte_size(params["nonce"]) > 20
  end

  test "member Google start is feature-gated and uses the shared validated callback" do
    disabled =
      :get
      |> conn("/api/auth/google/member/start", %{"redirect_to" => "/en/tickers/AAPL"})
      |> StonksBackendWeb.Router.call(@opts)

    assert disabled.status == 404
    assert disabled.resp_body == "Google OAuth member sign-in is not configured."

    Application.put_env(:stonks_backend, :settings,
      public_base_url: "https://stonks.example",
      ticker_member_features_enabled: "true",
      google_oauth_client_id: "client-id",
      google_oauth_client_secret: "client-secret"
    )

    conn =
      :get
      |> conn("/api/auth/google/member/start", %{"redirect_to" => "https://evil.example"})
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 302
    location = get_resp_header(conn, "location") |> List.first()
    params = location |> URI.parse() |> Map.fetch!(:query) |> URI.decode_query()
    assert params["redirect_uri"] == "https://stonks.example/api/auth/google/callback"
    assert byte_size(params["state"]) > 20
    assert byte_size(params["nonce"]) > 20
  end

  test "google callback preserves error redirect and rejects invalid state" do
    conn =
      :get
      |> conn("/api/auth/google/callback", %{"error" => String.duplicate("a", 300)})
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 302
    [location] = get_resp_header(conn, "location")
    assert location == "/admin/login?oauth_error=#{String.duplicate("a", 256)}"

    missing =
      :get
      |> conn("/api/auth/google/callback")
      |> StonksBackendWeb.Router.call(@opts)

    assert missing.status == 400
    assert missing.resp_body == "Missing Google OAuth callback parameters."

    unconfigured =
      :get
      |> conn("/api/auth/google/callback", %{"code" => "code", "state" => "state"})
      |> StonksBackendWeb.Router.call(@opts)

    assert unconfigured.status == 404
    assert unconfigured.resp_body == "Google OAuth admin login is not configured."

    Application.put_env(:stonks_backend, :settings,
      google_oauth_admin_enabled: "true",
      google_oauth_client_id: "client-id",
      google_oauth_client_secret: "client-secret"
    )

    invalid_state =
      :get
      |> conn("/api/auth/google/callback", %{"code" => "code", "state" => "state"})
      |> StonksBackendWeb.Router.call(@opts)

    assert invalid_state.status == 400
    assert invalid_state.resp_body == "Invalid or expired OAuth state."
  end
end
