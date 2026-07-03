defmodule StonksBackendWeb.CORSPlugTest do
  use ExUnit.Case, async: false
  import Plug.Conn
  import Plug.Test

  setup do
    original = Application.get_env(:stonks_backend, :settings)

    Application.put_env(:stonks_backend, :settings,
      app_env: "development",
      public_base_url: "https://stonks.example",
      dev_cors_origins: "http://localhost:5173"
    )

    on_exit(fn ->
      if is_nil(original) do
        Application.delete_env(:stonks_backend, :settings)
      else
        Application.put_env(:stonks_backend, :settings, original)
      end
    end)
  end

  test "allowed origins receive credentialed CORS headers" do
    conn =
      :get
      |> conn("/api/public/health")
      |> put_req_header("origin", "http://localhost:5173")
      |> StonksBackendWeb.Endpoint.call([])

    assert conn.status == 200
    assert get_resp_header(conn, "access-control-allow-origin") == ["http://localhost:5173"]
    assert get_resp_header(conn, "access-control-allow-credentials") == ["true"]
    assert get_resp_header(conn, "vary") == ["Origin"]
  end

  test "disallowed origins do not receive credentialed CORS headers" do
    conn =
      :get
      |> conn("/api/public/health")
      |> put_req_header("origin", "https://evil.example")
      |> StonksBackendWeb.Endpoint.call([])

    assert conn.status == 200
    assert get_resp_header(conn, "access-control-allow-origin") == []
    assert get_resp_header(conn, "access-control-allow-credentials") == []
  end

  test "same-origin requests without an origin header omit CORS headers" do
    conn =
      :get
      |> conn("/api/public/health")
      |> StonksBackendWeb.Endpoint.call([])

    assert conn.status == 200
    assert get_resp_header(conn, "access-control-allow-origin") == []
    assert get_resp_header(conn, "access-control-allow-credentials") == []
  end
end
