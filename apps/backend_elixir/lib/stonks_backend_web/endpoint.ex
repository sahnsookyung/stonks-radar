defmodule StonksBackendWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :stonks_backend

  plug Plug.RequestId
  plug Plug.Telemetry, event_prefix: [:phoenix, :endpoint]

  plug CORSPlug

  plug Plug.Parsers,
    parsers: [:urlencoded, :multipart, :json],
    pass: ["*/*"],
    body_reader: {__MODULE__, :read_body, []},
    json_decoder: Phoenix.json_library()

  plug Plug.MethodOverride
  plug Plug.Head
  plug :fetch_request_cookies
  plug StonksBackendWeb.Router

  defp fetch_request_cookies(conn, _opts), do: Plug.Conn.fetch_cookies(conn)

  def read_body(conn, opts) do
    case Plug.Conn.read_body(conn, opts) do
      {:ok, body, conn} -> {:ok, body, maybe_cache_raw_body(conn, body)}
      {:more, body, conn} -> {:more, body, maybe_cache_raw_body(conn, body)}
      other -> other
    end
  end

  def raw_body(conn) do
    conn.private
    |> Map.get(:stonks_raw_body, [])
    |> IO.iodata_to_binary()
  end

  defp maybe_cache_raw_body(%{request_path: "/api/internal/news/email-alerts"} = conn, body) do
    cached = Map.get(conn.private, :stonks_raw_body, [])
    Plug.Conn.put_private(conn, :stonks_raw_body, [cached, body])
  end

  defp maybe_cache_raw_body(conn, _body), do: conn
end
