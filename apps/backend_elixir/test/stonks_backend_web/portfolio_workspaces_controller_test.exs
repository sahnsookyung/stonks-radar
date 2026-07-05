defmodule StonksBackendWeb.PortfolioWorkspacesControllerTest do
  use ExUnit.Case, async: false
  import Plug.Conn
  import Plug.Test

  alias StonksBackend.{Accounts, Repo, Sql}

  @opts StonksBackendWeb.Router.init([])

  test "portfolio workspace read requires authentication" do
    conn =
      :get
      |> conn("/api/portfolio-workspaces/demo-growth-income")
      |> dispatch()

    assert conn.status == 401
    assert Jason.decode!(conn.resp_body)["detail"] == "Not authenticated"
  end

  @tag :db
  test "portfolio workspace saves and loads per authenticated user" do
    {:ok, _repo_pid} = start_repo()
    :ok = Ecto.Adapters.SQL.Sandbox.checkout(Repo)
    user_id = insert_user!()
    workspace = workspace_payload("demo-growth-income")

    put_conn =
      :put
      |> auth_json_conn("/api/portfolio-workspaces/demo-growth-income", user_id, %{
        workspace: workspace
      })
      |> StonksBackendWeb.Endpoint.call([])

    assert put_conn.status == 200
    put_body = Jason.decode!(put_conn.resp_body)
    assert put_body["portfolio_id"] == "demo-growth-income"
    assert put_body["workspace"]["portfolio"]["portfolioId"] == "demo-growth-income"
    assert put_body["workspace"]["manualInstruments"] == []

    get_conn =
      :get
      |> auth_conn("/api/portfolio-workspaces/demo-growth-income", user_id)
      |> dispatch()

    assert get_conn.status == 200
    get_body = Jason.decode!(get_conn.resp_body)
    assert get_body["workspace"]["assumptions"]["name"] == "Baseline"
    assert get_body["workspace"]["reviewRequests"] == []
  end

  defp dispatch(conn) do
    conn
    |> fetch_query_params()
    |> StonksBackendWeb.Router.call(@opts)
  end

  defp auth_json_conn(method, path, user_id, body) do
    conn =
      method
      |> conn(path, Jason.encode!(body))
      |> put_req_header("content-type", "application/json")

    put_auth(conn, user_id, csrf: true)
  end

  defp auth_conn(method, path, user_id) do
    method
    |> conn(path)
    |> put_auth(user_id, csrf: false)
  end

  defp put_auth(conn, user_id, opts) do
    {session_conn, csrf_token} = Accounts.create_session(conn(:get, "/"), user_id, "viewer")
    session_cookie = session_conn.resp_cookies[Accounts.session_cookie()].value

    conn =
      conn
      |> put_req_cookie(Accounts.session_cookie(), session_cookie)
      |> put_req_header("accept", "application/json")

    if Keyword.get(opts, :csrf, false) do
      put_req_header(conn, "x-csrf-token", csrf_token)
    else
      conn
    end
  end

  defp insert_user! do
    user_id = Ecto.UUID.generate()

    Sql.execute(
      """
      insert into app_user(id, email, password_hash, role, active, totp_required)
      values ($1, $2, 'not-used', 'viewer', true, false)
      """,
      [Ecto.UUID.dump!(user_id), "portfolio-#{System.unique_integer([:positive])}@example.com"]
    )

    user_id
  end

  defp workspace_payload(portfolio_id) do
    %{
      "version" => 1,
      "portfolio" => %{
        "portfolioId" => portfolio_id,
        "name" => "Demo Growth Income",
        "baseCurrency" => "USD",
        "holdings" => [],
        "transactions" => [],
        "taxLots" => [],
        "targetAllocation" => [],
        "goal" => %{"monthlyContribution" => 0}
      },
      "manualInstruments" => [],
      "reviewRequests" => [],
      "assumptions" => %{"name" => "Baseline"}
    }
  end

  defp start_repo do
    case Process.whereis(Repo) do
      nil -> {:ok, start_supervised!(Repo)}
      pid -> {:ok, pid}
    end
  end
end
