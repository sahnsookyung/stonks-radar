defmodule StonksBackend.Accounts do
  @moduledoc "Account/session compatibility over the preserved `app_user` and `app_session` tables."

  import Plug.Conn

  alias StonksBackend.Accounts.Crypto
  alias StonksBackend.{Repo, Settings, Sql}

  @session_cookie "frw_session"
  @csrf_cookie "frw_csrf"
  @session_max_age 12 * 60 * 60
  @admin_root_path "/admin"
  @max_session_token_bytes 128
  @max_csrf_token_bytes 128
  @csrf_hash_bytes 64
  @max_redirect_path_chars 256

  def session_cookie, do: @session_cookie
  def csrf_cookie, do: @csrf_cookie
  def session_max_age, do: @session_max_age

  def bootstrap_admin do
    case bootstrap_admin_config() do
      {:ok, config} ->
        case Repo.transaction(fn -> insert_bootstrap_admin(config) end) do
          {:ok, result} -> result
          {:error, _} -> :unavailable
        end

      {:error, :missing_bootstrap_credentials} ->
        :skipped
    end
  rescue
    _ -> :unavailable
  end

  def bootstrap_admin_config do
    password = Settings.get(:admin_bootstrap_password)
    totp_secret = Settings.get(:admin_totp_secret)

    if Settings.present?(password) and Settings.present?(totp_secret) do
      {:ok,
       %{
         email: normalize_email(Settings.get(:admin_email, "owner@example.com")),
         password: password,
         totp_secret: totp_secret
       }}
    else
      {:error, :missing_bootstrap_credentials}
    end
  end

  def authenticate(email, password, totp_code \\ nil) do
    row =
      Sql.one(
        """
        select u.id, u.email, u.password_hash, u.role, u.totp_required, t.secret_ciphertext
        from app_user u
        left join user_totp_secret t on t.user_id = u.id
        where u.email = $1 and u.active = true
        """,
        [email]
      )

    cond do
      is_nil(row) or not Crypto.verify_password(password, row["password_hash"]) ->
        {:error, :invalid_credentials}

      row["role"] in ["owner", "admin"] and row["totp_required"] and blank?(totp_code) ->
        {:error, :totp_required}

      row["role"] in ["owner", "admin"] and row["totp_required"] and
          not Crypto.verify_totp(row["secret_ciphertext"], totp_code) ->
        {:error, :invalid_totp}

      true ->
        {:ok, row}
    end
  end

  def create_session(conn, user_id, role, opts \\ []) do
    token = Crypto.new_token()
    csrf_token = Crypto.new_token()
    expose_csrf = Keyword.get(opts, :expose_csrf_cookie, false)
    persist = Keyword.get(opts, :persist, true)

    case persist_session(persist, user_id, role, token, csrf_token) do
      {:ok, _session_id} ->
        conn =
          put_resp_cookie(conn, @session_cookie, token,
            http_only: true,
            secure: Settings.production?(),
            same_site: "Lax",
            max_age: @session_max_age,
            path: "/"
          )

        conn =
          if expose_csrf do
            put_resp_cookie(conn, @csrf_cookie, csrf_token,
              http_only: false,
              secure: Settings.production?(),
              same_site: "Lax",
              max_age: 5 * 60,
              path: "/"
            )
          else
            conn
          end

        {conn, csrf_token}

      {:error, reason} ->
        {:error, reason}
    end
  end

  def clear_session(conn) do
    conn
    |> delete_resp_cookie(@session_cookie, path: "/")
    |> delete_resp_cookie(@csrf_cookie, path: "/")
  end

  def current_user(conn) do
    conn = fetch_cookies(conn)
    token = conn.cookies[@session_cookie]

    if blank?(token) do
      {:error, :not_authenticated}
    else
      current_user_by_token(token)
    end
  end

  defp current_user_by_token(token) do
    if not valid_session_token?(token) do
      {:error, :invalid_session}
    else
      row =
        Sql.one(
          """
          select s.id as session_id, s.csrf_hash, s.role, u.id as user_id, u.email, u.active
          from app_session s
          join app_user u on u.id = s.user_id
          where s.session_hash = $1 and s.expires_at > now()
          """,
          [Crypto.hash_secret(token)]
        )

      if row && row["active"] do
        {:ok,
         %{
           id: to_string(row["user_id"]),
           email: row["email"],
           role: row["role"],
           session_id: to_string(row["session_id"]),
           csrf_hash: row["csrf_hash"]
         }}
      else
        {:error, :invalid_session}
      end
    end
  end

  def require_role(conn, roles) do
    with {:ok, user} <- current_user(conn),
         true <- user.role in roles do
      {:ok, user}
    else
      {:error, reason} -> {:error, reason}
      false -> {:error, :insufficient_role}
    end
  end

  def require_csrf(conn, roles) do
    with {:ok, user} <- require_role(conn, roles),
         token when is_binary(token) <- get_req_header(conn, "x-csrf-token") |> List.first(),
         true <- valid_csrf_token?(token, user.csrf_hash) do
      {:ok, user}
    else
      {:error, reason} -> {:error, reason}
      _ -> {:error, :invalid_csrf}
    end
  end

  def valid_csrf_token?(token, csrf_hash) when is_binary(token) and is_binary(csrf_hash) do
    if valid_csrf_token_value?(token) and valid_stored_csrf_hash?(csrf_hash) do
      candidate = Crypto.hash_secret(token)

      Plug.Crypto.secure_compare(candidate, csrf_hash)
    else
      false
    end
  end

  def valid_csrf_token?(_, _), do: false

  def delete_session(session_id) do
    Sql.execute("delete from app_session where id = $1", [session_id])
  end

  def google_allowed?(email) do
    normalized = String.downcase(String.trim(email || ""))
    domain = email_domain(normalized)

    allowed_emails =
      Settings.google_allowed_emails()
      |> Enum.map(&normalize_email/1)

    allowed_domains =
      Settings.google_allowed_domains()
      |> Enum.map(&normalize_domain/1)

    normalized in allowed_emails or (domain != "" and domain in allowed_domains)
  end

  def consume_google_state(state) do
    row =
      Sql.one(
        """
        update oauth_login_state
        set used_at = now()
        where state_hash = $1
          and provider = 'google'
          and used_at is null
          and expires_at > now()
        returning state_hash, nonce_hash, redirect_to, purpose
        """,
        [Crypto.hash_secret(state)]
      )

    if row, do: {:ok, row}, else: {:error, :invalid_oauth_state}
  end

  def fetch_google_profile(code, expected_nonce_hash) do
    with {:ok, token_payload} <- exchange_google_code(code),
         {:ok, id_token} <- require_id_token(token_payload),
         {:ok, claims} <- fetch_google_claims(id_token),
         :ok <- validate_google_claims(claims, expected_nonce_hash) do
      {:ok, claims}
    end
  end

  def upsert_google_admin_user(profile) when is_map(profile) do
    email = profile |> Map.get("email", "") |> normalize_email()
    subject = profile |> Map.get("sub", "") |> to_string() |> String.trim()
    email_verified = google_email_verified?(profile["email_verified"])

    cond do
      email == "" or subject == "" or not email_verified or not google_allowed?(email) ->
        {:error, :google_account_not_authorized}

      true ->
        role =
          if email == normalize_email(Settings.get(:admin_email, "owner@example.com")),
            do: "owner",
            else: "admin"

        user =
          Sql.one(
            """
            insert into app_user(
              email, password_hash, role, active, totp_required,
              auth_provider, external_subject, last_login_at, auth_metadata
            )
            values (
              $1, $2, $3, true, false,
              'google', $4, now(), $5::text::jsonb
            )
            on conflict (email) do update set
              role = case
                when app_user.role = 'owner' then app_user.role
                else excluded.role
              end,
              auth_provider = 'google',
              external_subject = excluded.external_subject,
              active = true,
              last_login_at = now(),
              auth_metadata = excluded.auth_metadata,
              updated_at = now()
            returning id, email, role
            """,
            [
              email,
              "oauth:google:#{Crypto.hash_secret(subject)}",
              role,
              subject,
              Jason.encode!(%{
                "name" => profile["name"],
                "picture" => profile["picture"],
                "email_verified" => profile["email_verified"]
              })
            ]
          )

        if user, do: {:ok, user}, else: {:error, :google_user_upsert_failed}
    end
  end

  def upsert_google_member_user(profile) when is_map(profile) do
    email = profile |> Map.get("email", "") |> normalize_email()
    subject = profile |> Map.get("sub", "") |> to_string() |> String.trim()

    if email == "" or subject == "" or not google_email_verified?(profile["email_verified"]) do
      {:error, :google_account_not_authorized}
    else
      user =
        Sql.one(
          """
          insert into app_user(
            email, password_hash, role, active, totp_required,
            auth_provider, external_subject, last_login_at, auth_metadata
          )
          values ($1, $2, 'member', true, false, 'google', $3, now(), $4::text::jsonb)
          on conflict (email) do update set
            role = case
              when app_user.role in ('owner','admin','editor','viewer') then app_user.role
              else 'member'
            end,
            auth_provider = 'google',
            external_subject = excluded.external_subject,
            active = true,
            last_login_at = now(),
            auth_metadata = excluded.auth_metadata,
            updated_at = now()
          returning id, email, role
          """,
          [
            email,
            "oauth:google:#{Crypto.hash_secret(subject)}",
            subject,
            Jason.encode!(%{
              "name" => profile["name"],
              "picture" => profile["picture"],
              "email_verified" => profile["email_verified"]
            })
          ]
        )

      if user, do: {:ok, user}, else: {:error, :google_user_upsert_failed}
    end
  end

  def upsert_google_user(profile, "admin"), do: upsert_google_admin_user(profile)
  def upsert_google_user(profile, "member"), do: upsert_google_member_user(profile)
  def upsert_google_user(_profile, _purpose), do: {:error, :invalid_oauth_state}

  def oauth_purpose_enabled?("admin"), do: Settings.google_oauth_enabled?()
  def oauth_purpose_enabled?("member"), do: Settings.google_member_oauth_enabled?()
  def oauth_purpose_enabled?(_purpose), do: false

  def google_config do
    enabled = Settings.google_oauth_enabled?()

    %{
      enabled: enabled,
      recommended: enabled,
      start_url: if(enabled, do: "/api/auth/google/start"),
      fallback_password_login: true,
      private_yahoo_admin_eligible: enabled and Settings.yahoo_admin_enabled?(),
      allowed_hint: google_allowed_hint()
    }
  end

  def safe_admin_redirect_path(path) do
    path =
      (path || @admin_root_path)
      |> to_string()
      |> String.slice(0, @max_redirect_path_chars)
      |> String.trim()

    if path == @admin_root_path or String.starts_with?(path, @admin_root_path <> "/") do
      path
    else
      @admin_root_path
    end
  end

  def safe_member_redirect_path(path) do
    path =
      (path || "/en/tickers/NVDA")
      |> to_string()
      |> String.slice(0, @max_redirect_path_chars)
      |> String.trim()

    if path in ["/en", "/ko"] or String.starts_with?(path, "/en/") or
         String.starts_with?(path, "/ko/") do
      path
    else
      "/en/tickers/NVDA"
    end
  end

  def safe_oauth_redirect_path(path, "admin"), do: safe_admin_redirect_path(path)
  def safe_oauth_redirect_path(path, "member"), do: safe_member_redirect_path(path)
  def safe_oauth_redirect_path(_path, _purpose), do: "/en/tickers/NVDA"

  def google_redirect_uri do
    base =
      Settings.get(:public_base_url, Settings.get(:app_base_url, "http://localhost:8000"))
      |> String.trim_trailing("/")

    path = Settings.get(:google_oauth_redirect_path, "/api/auth/google/callback")
    path = if String.starts_with?(path, "/"), do: path, else: "/" <> path
    base <> path
  end

  defp exchange_google_code(code) do
    case Req.post(Settings.get(:google_oauth_token_url, "https://oauth2.googleapis.com/token"),
           form: %{
             "code" => code,
             "client_id" => Settings.get(:google_oauth_client_id),
             "client_secret" => Settings.get(:google_oauth_client_secret),
             "redirect_uri" => google_redirect_uri(),
             "grant_type" => "authorization_code"
           },
           headers: [{"accept", "application/json"}],
           receive_timeout: 12_000,
           retry: false
         ) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_map(body) ->
        {:ok, body}

      {:ok, %{status: status}} when status >= 400 ->
        {:error, {:bad_gateway, "Google OAuth token exchange failed."}}

      {:error, exception} ->
        {:error,
         {:bad_gateway, "Google OAuth token exchange failed: #{Exception.message(exception)}"}}
    end
  end

  defp require_id_token(%{"id_token" => id_token}) when is_binary(id_token) and id_token != "",
    do: {:ok, id_token}

  defp require_id_token(_),
    do: {:error, {:bad_gateway, "Google OAuth token response did not include an ID token."}}

  defp fetch_google_claims(id_token) do
    case Req.get(
           Settings.get(:google_oauth_tokeninfo_url, "https://oauth2.googleapis.com/tokeninfo"),
           params: %{id_token: id_token},
           headers: [{"accept", "application/json"}],
           receive_timeout: 12_000,
           retry: false
         ) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_map(body) ->
        {:ok, body}

      {:ok, %{status: status}} when status >= 400 ->
        {:error, {:bad_gateway, "Google OAuth ID token validation failed."}}

      {:error, exception} ->
        {:error,
         {:bad_gateway,
          "Google OAuth ID token validation failed: #{Exception.message(exception)}"}}
    end
  end

  defp validate_google_claims(claims, expected_nonce_hash) do
    cond do
      claims["aud"] != Settings.get(:google_oauth_client_id) ->
        {:error, {:forbidden, "Google OAuth audience mismatch."}}

      Crypto.hash_secret(to_string(claims["nonce"] || "")) != expected_nonce_hash ->
        {:error, {:forbidden, "Google OAuth nonce mismatch."}}

      true ->
        :ok
    end
  end

  defp google_email_verified?(value), do: value in [true, "true", "True", "1", 1]

  defp google_allowed_hint do
    emails = Settings.google_allowed_emails()
    domains = Settings.google_allowed_domains()

    cond do
      emails != [] -> "#{length(emails)} explicit admin email(s)"
      domains != [] -> "#{length(domains)} allowed domain(s)"
      true -> nil
    end
  end

  defp normalize_email(value),
    do: value |> to_string() |> String.trim() |> String.downcase()

  defp normalize_domain(value),
    do: value |> to_string() |> String.trim() |> String.trim_leading("@") |> String.downcase()

  defp email_domain(value) do
    case String.split(value, "@", parts: 2) do
      [_local, domain] -> normalize_domain(domain)
      _ -> ""
    end
  end

  defp insert_bootstrap_admin(config) do
    existing =
      Sql.scalar("select id from app_user where email = $1", [
        config.email
      ])

    if is_nil(existing) do
      user_id =
        Sql.scalar(
          """
          insert into app_user(email, password_hash, role, totp_required)
          values ($1, $2, 'owner', true)
          returning id
          """,
          [config.email, Crypto.hash_password(config.password)]
        )

      Sql.execute(
        "insert into user_totp_secret(user_id, secret_ciphertext) values ($1, $2)",
        [user_id, config.totp_secret]
      )

      :created
    else
      :already_exists
    end
  end

  defp persist_session(false, _user_id, _role, _token, _csrf_token), do: {:ok, :not_persisted}

  defp persist_session(true, user_id, role, token, csrf_token) do
    session_id =
      Sql.scalar(
        """
        insert into app_session(user_id, session_hash, csrf_hash, role, expires_at)
        values ($1, $2, $3, $4, now() + interval '12 hours')
        returning id
        """,
        [uuid_param(user_id), Crypto.hash_secret(token), Crypto.hash_secret(csrf_token), role]
      )

    if is_nil(session_id), do: {:error, :session_unavailable}, else: {:ok, session_id}
  rescue
    _ -> {:error, :session_unavailable}
  end

  defp uuid_param(value) when is_binary(value) and byte_size(value) == 16, do: value

  defp uuid_param(value) do
    case Ecto.UUID.cast(value) do
      {:ok, uuid} -> Ecto.UUID.dump!(uuid)
      :error -> value
    end
  end

  defp valid_session_token?(token), do: valid_url_token?(token, @max_session_token_bytes)
  defp valid_csrf_token_value?(token), do: valid_url_token?(token, @max_csrf_token_bytes)

  defp valid_url_token?(token, max_bytes) when is_binary(token),
    do: byte_size(token) in 1..max_bytes and String.match?(token, ~r/^[A-Za-z0-9_-]+$/)

  defp valid_url_token?(_, _), do: false

  defp valid_stored_csrf_hash?(hash) when is_binary(hash),
    do: byte_size(hash) == @csrf_hash_bytes and String.match?(hash, ~r/^[0-9a-f]{64}$/)

  defp blank?(value) when is_binary(value), do: String.trim(value) == ""
  defp blank?(value), do: value in [nil, ""]
end
