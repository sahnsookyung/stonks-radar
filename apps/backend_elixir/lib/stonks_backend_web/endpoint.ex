defmodule StonksBackendWeb.Endpoint do
  use Phoenix.Endpoint, otp_app: :stonks_backend

  plug Plug.RequestId
  plug Plug.Telemetry, event_prefix: [:phoenix, :endpoint]

  plug CORSPlug

  plug Plug.Parsers,
    parsers: [:urlencoded, :multipart, :json],
    pass: ["*/*"],
    json_decoder: Phoenix.json_library()

  plug Plug.MethodOverride
  plug Plug.Head
  plug :fetch_request_cookies
  plug StonksBackendWeb.Router

  defp fetch_request_cookies(conn, _opts), do: Plug.Conn.fetch_cookies(conn)
end
