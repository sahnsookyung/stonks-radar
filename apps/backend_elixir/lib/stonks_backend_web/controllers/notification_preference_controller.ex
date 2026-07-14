defmodule StonksBackendWeb.NotificationPreferenceController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{Accounts, Settings, TickerNotifications}

  @roles ~w(owner admin editor viewer member)

  def show(conn, _params) do
    with_auth(conn, fn user ->
      case TickerNotifications.preferences(user.id) do
        {:ok, preferences} -> no_store_json(conn, preferences)
        _ -> unavailable(conn)
      end
    end)
  end

  def update(conn, params) do
    with_csrf(conn, fn user ->
      case TickerNotifications.update_preferences(user.id, params) do
        {:ok, preferences} -> no_store_json(conn, preferences)
        _ -> unavailable(conn)
      end
    end)
  end

  def unsubscribe(conn, %{"token" => token}) do
    case TickerNotifications.unsubscribe(token) do
      :ok ->
        json(conn, %{status: "unsubscribed"})

      {:error, :not_found} ->
        conn |> put_status(404) |> json(%{detail: "Unsubscribe link not found"})
    end
  end

  def unsubscribe(conn, _params),
    do: conn |> put_status(422) |> json(%{detail: "token is required"})

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
    do:
      conn |> put_status(503) |> no_store_json(%{detail: "Notification preferences unavailable"})

  defp no_store_json(conn, payload),
    do: conn |> put_resp_header("cache-control", "no-store") |> json(payload)
end
