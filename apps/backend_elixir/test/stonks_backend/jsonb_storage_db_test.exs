defmodule StonksBackend.JsonbStorageDbTest do
  use ExUnit.Case, async: false

  alias StonksBackend.{
    Accounts,
    Audit,
    PortfolioWorkspaces,
    Repo,
    Sql,
    TickerAlerts,
    TickerProviderConnections,
    TickerWorkspaces
  }

  @tag :db
  test "user-owned and security metadata persist as JSON objects" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)

    original_settings = Application.get_env(:stonks_backend, :settings)

    on_exit(fn ->
      if Process.whereis(Repo), do: Ecto.Adapters.SQL.Sandbox.checkin(Repo)

      if is_nil(original_settings) do
        Application.delete_env(:stonks_backend, :settings)
      else
        Application.put_env(:stonks_backend, :settings, original_settings)
      end
    end)

    suffix = System.unique_integer([:positive])
    admin_email = "json-admin-#{suffix}@example.com"
    member_email = "json-member-#{suffix}@example.com"

    Application.put_env(:stonks_backend, :settings,
      admin_email: admin_email,
      google_oauth_allowed_emails: admin_email
    )

    assert {:ok, admin} =
             Accounts.upsert_google_admin_user(google_profile(admin_email, "admin-#{suffix}"))

    assert jsonb_type("app_user", "auth_metadata", admin["id"]) == "object"

    assert {:ok, member} =
             Accounts.upsert_google_member_user(google_profile(member_email, "member-#{suffix}"))

    assert jsonb_type("app_user", "auth_metadata", member["id"]) == "object"

    assert {:ok, preserved_admin} =
             Accounts.upsert_google_member_user(
               google_profile(admin_email, "admin-member-#{suffix}")
             )

    assert preserved_admin["role"] == "owner"

    ticker_workspace = %{
      "version" => 1,
      "watchlist" => ["AAPL"],
      "notes" => %{},
      "comparisons" => []
    }

    assert {:ok, %{workspace: ^ticker_workspace}} =
             TickerWorkspaces.put(member["id"], ticker_workspace, 0)

    assert jsonb_type("ticker_workspace", "workspace", member["id"], "user_id") == "object"

    portfolio_workspace = %{
      "version" => 1,
      "portfolio" => %{"portfolioId" => "local-portfolio"},
      "manualInstruments" => [],
      "reviewRequests" => [],
      "assumptions" => %{}
    }

    assert {:ok, %{workspace: ^portfolio_workspace}} =
             PortfolioWorkspaces.put(member["id"], "local-portfolio", portfolio_workspace)

    assert jsonb_type("portfolio_workspace", "workspace", member["id"], "user_id") ==
             "object"

    key = :crypto.strong_rand_bytes(32)
    token = "private-token-#{suffix}"

    assert {:ok, _connection} =
             TickerProviderConnections.connect(member["id"], token,
               key: key,
               verify_fun: fn _token ->
                 {:ok, %{entitlement: "delayed", delay: 15, quota: 100}}
               end
             )

    assert jsonb_type(
             "user_provider_connection",
             "verification_metadata",
             member["id"],
             "user_id"
           ) == "object"

    assert {:ok, ^token} = TickerProviderConnections.token_for(member["id"], key: key)

    assert {:ok, rule} =
             TickerAlerts.create_rule(member["id"], %{
               "symbol" => "AAPL",
               "rule_type" => "price_threshold",
               "configuration" => %{"operator" => "above", "value" => 200}
             })

    assert jsonb_type("ticker_alert_rule", "configuration", rule["id"]) == "object"

    assert {:ok, updated_rule} =
             TickerAlerts.update_rule(member["id"], rule["id"], %{
               "symbol" => "AAPL",
               "rule_type" => "price_threshold",
               "configuration" => %{"operator" => "below", "value" => 150}
             })

    assert updated_rule["configuration"] == %{"operator" => "below", "value" => 150}

    event_rule = Map.put(rule, "user_id", member["id"])

    event_key = "price:#{suffix}"

    assert {:ok, %{id: event_id, deduplicated: false}} =
             TickerAlerts.create_event(
               event_rule,
               event_key,
               ~U[2026-07-15 00:00:00Z],
               "threshold matched",
               %{"price" => 201}
             )

    assert is_binary(event_id)

    assert jsonb_type("ticker_alert_event", "payload", event_key, "source_event_key") ==
             "object"

    assert %Postgrex.Result{num_rows: 1} =
             Audit.write("jsonb.storage_test",
               user: %{id: member["id"], role: "member"},
               target_table: "ticker_workspace",
               target_pk: member_email,
               after: %{"revision" => 1}
             )

    assert Sql.scalar(
             "select jsonb_typeof(after_json) from audit_log where action = $1 order by created_at desc limit 1",
             ["jsonb.storage_test"]
           ) == "object"
  end

  defp google_profile(email, subject) do
    %{
      "email" => email,
      "sub" => subject,
      "email_verified" => true,
      "name" => "JSON storage test",
      "picture" => "https://example.com/avatar.png"
    }
  end

  defp jsonb_type(table, column, id, id_column \\ "id") do
    Sql.scalar("select jsonb_typeof(#{column}) from #{table} where #{id_column} = $1", [id])
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end
end
