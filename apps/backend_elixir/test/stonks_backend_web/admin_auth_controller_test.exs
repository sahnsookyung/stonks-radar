defmodule StonksBackendWeb.AdminAuthControllerTest do
  use ExUnit.Case, async: false
  import Plug.Conn
  import Plug.Test

  alias StonksBackend.{Accounts, Repo, Sql}

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

  @tag :db
  test "member sessions receive forbidden responses from admin routes" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)
    user_id = Ecto.UUID.generate()

    Sql.execute(
      """
      insert into app_user(id, email, password_hash, role, active, totp_required)
      values ($1, $2, 'not-used', 'member', true, false)
      """,
      [Ecto.UUID.dump!(user_id), "member-#{System.unique_integer([:positive])}@example.com"]
    )

    {session_conn, _csrf_token} = Accounts.create_session(conn(:get, "/"), user_id, "member")
    session_cookie = session_conn.resp_cookies[Accounts.session_cookie()].value

    conn =
      :get
      |> conn("/api/admin/dashboard")
      |> put_req_cookie(Accounts.session_cookie(), session_cookie)
      |> fetch_query_params()
      |> StonksBackendWeb.Router.call(@opts)

    assert conn.status == 403
    assert Jason.decode!(conn.resp_body) == %{"detail" => "Insufficient role"}
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end
end
