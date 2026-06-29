defmodule StonksBackendWeb.AuthController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{Accounts, Audit, Settings}

  def google_config(conn, _params), do: json(conn, Accounts.google_config())

  def google_start(conn, params) do
    if Settings.google_oauth_enabled?() do
      state = StonksBackend.Accounts.Crypto.new_token()
      nonce = StonksBackend.Accounts.Crypto.new_token()
      redirect_to = Accounts.safe_admin_redirect_path(params["redirect_to"] || "/admin")

      persist_google_state(state, nonce, redirect_to)

      query =
        URI.encode_query(%{
          client_id: Settings.get(:google_oauth_client_id),
          redirect_uri: Accounts.google_redirect_uri(),
          response_type: "code",
          scope: "openid email profile",
          state: state,
          nonce: nonce,
          prompt: "select_account",
          include_granted_scopes: "true"
        })

      redirect(conn, external: "https://accounts.google.com/o/oauth2/v2/auth?#{query}")
    else
      conn |> send_resp(404, "Google OAuth admin login is not configured.")
    end
  end

  defp persist_google_state(state, nonce, redirect_to) do
    StonksBackend.Sql.execute(
      """
      insert into oauth_login_state(state_hash, nonce_hash, provider, redirect_to, expires_at)
      values ($1, $2, 'google', $3, now() + interval '10 minutes')
      on conflict (state_hash) do nothing
      """,
      [
        StonksBackend.Accounts.Crypto.hash_secret(state),
        StonksBackend.Accounts.Crypto.hash_secret(nonce),
        redirect_to
      ]
    )
  rescue
    _ -> :ok
  end

  def google_callback(conn, %{"error" => error}) do
    redirect(conn, to: "/admin/login?#{URI.encode_query(%{oauth_error: oauth_error(error)})}")
  end

  def google_callback(conn, params) do
    cond do
      blank?(params["code"]) or blank?(params["state"]) ->
        send_resp(conn, 400, "Missing Google OAuth callback parameters.")

      not Settings.google_oauth_enabled?() ->
        send_resp(conn, 404, "Google OAuth admin login is not configured.")

      true ->
        send_resp(
          conn,
          501,
          "Google OAuth callback exchange is not enabled in this migration slice."
        )
    end
  end

  def login(conn, %{"email" => email, "password" => password} = params) do
    case Accounts.authenticate(email, password, params["totp_code"]) do
      {:ok, user} ->
        case Accounts.create_session(conn, to_string(user["id"]), user["role"]) do
          {%Plug.Conn{} = conn, csrf_token} ->
            Audit.write("auth.login_succeeded",
              target_table: "app_user",
              target_pk: to_string(user["id"]),
              after: %{role: user["role"]}
            )

            json(conn, %{status: "ok", csrf_token: csrf_token})

          {:error, :session_unavailable} ->
            conn |> put_status(503) |> json(%{detail: "Session storage unavailable"})
        end

      {:error, :totp_required} ->
        json(conn, %{status: "totp_required", message: "TOTP code required for owner/admin."})

      {:error, :invalid_totp} ->
        conn |> put_status(401) |> send_resp(401, "Invalid TOTP code")

      _ ->
        conn |> put_status(401) |> send_resp(401, "Invalid credentials")
    end
  end

  def logout(conn, _params) do
    case Accounts.current_user(conn) do
      {:ok, user} ->
        Accounts.delete_session(user.session_id)

        Audit.write("auth.logout",
          user: user,
          target_table: "app_session",
          target_pk: user.session_id
        )

        conn
        |> Accounts.clear_session()
        |> json(%{status: "ok"})

      {:error, :invalid_session} ->
        conn |> put_status(401) |> json(%{detail: "Invalid session"})

      _ ->
        conn |> put_status(401) |> json(%{detail: "Not authenticated"})
    end
  end

  def me(conn, _params) do
    case Accounts.current_user(conn) do
      {:ok, user} -> json(conn, %{id: user.id, email: user.email, role: user.role})
      {:error, :invalid_session} -> conn |> put_status(401) |> json(%{detail: "Invalid session"})
      _ -> conn |> put_status(401) |> json(%{detail: "Not authenticated"})
    end
  end

  defp oauth_error(error),
    do: error |> to_string() |> String.slice(0, 256)

  defp blank?(value) when is_binary(value), do: String.trim(value) == ""
  defp blank?(value), do: value in [nil, ""]
end
