defmodule StonksBackendWeb.TickerAlertController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{Accounts, Settings, TickerAlerts}

  @roles ~w(owner admin editor viewer member)

  def index(conn, _params), do: with_auth(conn, &list_rules(conn, &1))
  def events(conn, _params), do: with_auth(conn, &list_events(conn, &1))

  def create(conn, params) do
    with_csrf(conn, fn user ->
      case TickerAlerts.create_rule(user.id, params) do
        {:ok, rule} -> conn |> put_status(201) |> no_store_json(rule)
        {:error, reason} -> rule_error(conn, reason)
      end
    end)
  end

  def update(conn, %{"id" => id} = params) do
    with_csrf(conn, fn user ->
      case TickerAlerts.update_rule(user.id, id, Map.delete(params, "id")) do
        {:ok, rule} ->
          no_store_json(conn, rule)

        {:error, :not_found} ->
          conn |> put_status(404) |> no_store_json(%{detail: "Alert rule not found"})

        {:error, reason} ->
          rule_error(conn, reason)
      end
    end)
  end

  def delete(conn, %{"id" => id}) do
    with_csrf(conn, fn user ->
      case TickerAlerts.delete_rule(user.id, id) do
        :ok ->
          send_resp(conn, 204, "")

        {:error, :not_found} ->
          conn |> put_status(404) |> no_store_json(%{detail: "Alert rule not found"})

        _ ->
          unavailable(conn)
      end
    end)
  end

  def read_event(conn, %{"id" => id}) do
    with_csrf(conn, fn user ->
      case TickerAlerts.mark_read(user.id, id) do
        {:ok, event} ->
          no_store_json(conn, event)

        {:error, :not_found} ->
          conn |> put_status(404) |> no_store_json(%{detail: "Alert event not found"})
      end
    end)
  end

  defp list_rules(conn, user) do
    case TickerAlerts.list_rules(user.id) do
      {:ok, rules} -> no_store_json(conn, %{rules: rules})
      _ -> unavailable(conn)
    end
  end

  defp list_events(conn, user) do
    case TickerAlerts.list_events(user.id) do
      {:ok, events} -> no_store_json(conn, %{events: events})
      _ -> unavailable(conn)
    end
  end

  defp rule_error(conn, reason)
       when reason in [
              :invalid_symbol,
              :invalid_rule_type,
              :invalid_configuration,
              :configuration_too_large,
              :invalid_cooldown,
              :invalid_rule
            ],
       do: conn |> put_status(422) |> no_store_json(%{detail: Atom.to_string(reason)})

  defp rule_error(conn, _reason), do: unavailable(conn)

  defp with_auth(conn, fun) do
    if Settings.ticker_member_features_enabled?() do
      case Accounts.require_role(conn, @roles) do
        {:ok, user} ->
          fun.(user)

        {:error, :insufficient_role} ->
          conn |> put_status(403) |> no_store_json(%{detail: "Insufficient role"})

        _ ->
          conn |> put_status(401) |> no_store_json(%{detail: "Not authenticated"})
      end
    else
      feature_disabled(conn)
    end
  end

  defp with_csrf(conn, fun) do
    if Settings.ticker_member_features_enabled?() do
      case Accounts.require_csrf(conn, @roles) do
        {:ok, user} ->
          fun.(user)

        {:error, :invalid_csrf} ->
          conn |> put_status(403) |> no_store_json(%{detail: "Invalid CSRF token"})

        {:error, :insufficient_role} ->
          conn |> put_status(403) |> no_store_json(%{detail: "Insufficient role"})

        _ ->
          conn |> put_status(401) |> no_store_json(%{detail: "Not authenticated"})
      end
    else
      feature_disabled(conn)
    end
  end

  defp feature_disabled(conn),
    do: conn |> put_status(404) |> no_store_json(%{detail: "Ticker member features disabled"})

  defp unavailable(conn),
    do: conn |> put_status(503) |> no_store_json(%{detail: "Ticker alerts unavailable"})

  defp no_store_json(conn, payload),
    do: conn |> put_resp_header("cache-control", "no-store") |> json(payload)
end
