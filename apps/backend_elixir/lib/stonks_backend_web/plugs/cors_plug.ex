defmodule CORSPlug do
  @moduledoc false
  import Plug.Conn

  alias StonksBackend.Settings

  def init(opts), do: opts

  def call(conn, _opts) do
    origin = get_req_header(conn, "origin") |> List.first()

    conn =
      if origin in Settings.cors_origins() do
        put_cors_headers(conn, origin)
      else
        conn
      end

    if conn.method == "OPTIONS" do
      conn |> send_resp(204, "") |> halt()
    else
      conn
    end
  end

  defp put_cors_headers(conn, origin) do
    conn
    |> put_resp_header("access-control-allow-origin", origin)
    |> put_resp_header("access-control-allow-credentials", "true")
    |> put_resp_header("access-control-allow-methods", "GET,POST,PATCH,DELETE,OPTIONS")
    |> put_resp_header(
      "access-control-allow-headers",
      "Content-Type,x-csrf-token,x-stonks-timestamp,x-stonks-nonce,x-stonks-email-signature"
    )
    |> put_resp_header("vary", "Origin")
  end
end
