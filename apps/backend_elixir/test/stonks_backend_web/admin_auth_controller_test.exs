defmodule StonksBackendWeb.AdminAuthControllerTest do
  use ExUnit.Case, async: true
  import Plug.Conn
  import Plug.Test

  @opts StonksBackendWeb.Router.init([])

  test "admin viewer routes require an authenticated session" do
    conn =
      :get
      |> conn("/api/admin/dashboard")
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 401
    assert Jason.decode!(conn.resp_body) == %{"detail" => "Not authenticated"}
  end

  test "admin CSRF routes still report unauthenticated before CSRF validation" do
    conn =
      :post
      |> conn("/api/admin/provider-budgets/main/kill-switch", %{enabled: true})
      |> put_req_header("x-csrf-token", "bad-token")
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 401
    assert Jason.decode!(conn.resp_body) == %{"detail" => "Not authenticated"}
  end

  test "release quarantine endpoint is admin and CSRF protected" do
    conn =
      :post
      |> conn("/api/admin/release-controls/quarantine", %{release_id: "abc123"})
      |> put_req_header("x-csrf-token", "bad-token")
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 401
    assert Jason.decode!(conn.resp_body) == %{"detail" => "Not authenticated"}
  end
end
