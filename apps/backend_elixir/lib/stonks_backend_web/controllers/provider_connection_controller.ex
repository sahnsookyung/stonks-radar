defmodule StonksBackendWeb.ProviderConnectionController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{Accounts, TickerProviderConnections}

  @roles ~w(owner admin editor viewer member)

  def show(conn, _params) do
    with_auth(conn, fn user ->
      case TickerProviderConnections.status(user.id) do
        {:ok, connection} ->
          no_store_json(conn, connection)

        {:error, :not_connected} ->
          no_store_json(conn, %{provider: "marketdata_app", status: "not_connected"})
      end
    end)
  end

  def create(conn, %{"token" => token}) do
    with_csrf(conn, fn user ->
      if TickerProviderConnections.enabled?() do
        case TickerProviderConnections.connect(user.id, token) do
          {:ok, connection} -> no_store_json(conn, connection)
          {:error, reason} -> provider_error(conn, reason)
        end
      else
        entitlement_required(conn)
      end
    end)
  end

  def create(conn, _params), do: validation_error(conn, "token is required")

  def delete(conn, _params) do
    with_csrf(conn, fn user ->
      case TickerProviderConnections.delete(user.id) do
        :ok -> no_store_json(conn, %{status: "deleted"})
        _ -> unavailable(conn)
      end
    end)
  end

  defp provider_error(conn, reason)
       when reason in [:invalid_credential, :provider_entitlement_required],
       do: conn |> put_status(422) |> no_store_json(%{detail: Atom.to_string(reason)})

  defp provider_error(conn, :provider_quota_exceeded),
    do: conn |> put_status(429) |> no_store_json(%{detail: "provider_quota_exceeded"})

  defp provider_error(conn, _reason), do: unavailable(conn)

  defp with_auth(conn, fun) do
    case Accounts.require_role(conn, @roles) do
      {:ok, user} ->
        fun.(user)

      {:error, :insufficient_role} ->
        conn |> put_status(403) |> no_store_json(%{detail: "Insufficient role"})

      _ ->
        conn |> put_status(401) |> no_store_json(%{detail: "Not authenticated"})
    end
  end

  defp with_csrf(conn, fun) do
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
  end

  defp entitlement_required(conn),
    do:
      conn
      |> put_status(403)
      |> no_store_json(%{
        status: "entitlement_required",
        detail: "Private market data requires provider approval and the production feature flag."
      })

  defp validation_error(conn, message),
    do: conn |> put_status(422) |> no_store_json(%{detail: message})

  defp unavailable(conn),
    do: conn |> put_status(503) |> no_store_json(%{detail: "Provider connection unavailable"})

  defp no_store_json(conn, payload),
    do: conn |> put_resp_header("cache-control", "no-store") |> json(payload)
end
