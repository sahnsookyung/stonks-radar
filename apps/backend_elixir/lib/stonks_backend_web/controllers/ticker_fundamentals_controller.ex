defmodule StonksBackendWeb.TickerFundamentalsController do
  use StonksBackendWeb, :controller

  alias StonksBackend.TickerFundamentals

  def show(conn, %{"symbol" => symbol}) do
    case TickerFundamentals.get(symbol) do
      {:ok, payload} ->
        conn |> put_resp_header("cache-control", "public, max-age=300") |> json(payload)

      {:error, :storage_unavailable} ->
        conn |> put_status(503) |> json(%{detail: "Fundamentals unavailable"})
    end
  end
end
