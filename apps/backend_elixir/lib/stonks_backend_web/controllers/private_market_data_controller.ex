defmodule StonksBackendWeb.PrivateMarketDataController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{Accounts, PrivateMarketData}

  @roles ~w(owner admin editor viewer member)

  def history(conn, params) do
    with_auth(conn, fn user ->
      user.id
      |> PrivateMarketData.history(params["symbol"], params["from"], params["to"])
      |> respond(conn)
    end)
  end

  def options(conn, params) do
    with_auth(conn, fn user ->
      user.id
      |> PrivateMarketData.options(params["symbol"], params["expiration"])
      |> respond(conn)
    end)
  end

  defp respond({:ok, payload, cache}, conn),
    do: no_store_json(conn, Map.put(payload, :cache, cache))

  defp respond({:error, :feature_disabled}, conn), do: entitlement_required(conn)

  defp respond({:error, reason}, conn)
       when reason in [:invalid_symbol, :invalid_date_range, :invalid_date],
       do: conn |> put_status(422) |> no_store_json(%{detail: Atom.to_string(reason)})

  defp respond({:error, reason}, conn)
       when reason in [:not_connected, :not_verified, :provider_entitlement_required],
       do:
         conn
         |> put_status(403)
         |> no_store_json(%{status: "entitlement_required", detail: Atom.to_string(reason)})

  defp respond({:error, :provider_quota_exceeded}, conn),
    do: conn |> put_status(429) |> no_store_json(%{detail: "provider_quota_exceeded"})

  defp respond(_error, conn),
    do: conn |> put_status(502) |> no_store_json(%{detail: "Private provider request failed"})

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

  defp entitlement_required(conn),
    do:
      conn
      |> put_status(403)
      |> no_store_json(%{
        status: "entitlement_required",
        detail: "Connect a verified private provider after delegated-use approval."
      })

  defp no_store_json(conn, payload),
    do: conn |> put_resp_header("cache-control", "private, no-store") |> json(payload)
end
