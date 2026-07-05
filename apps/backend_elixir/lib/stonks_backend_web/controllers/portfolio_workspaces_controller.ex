defmodule StonksBackendWeb.PortfolioWorkspacesController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{Accounts, PortfolioWorkspaces}

  @roles ~w(owner admin editor viewer)

  def show(conn, %{"portfolio_id" => portfolio_id}) do
    with_auth(conn, fn user ->
      case PortfolioWorkspaces.get(user.id, portfolio_id) do
        {:ok, payload} ->
          conn
          |> put_public_no_store_headers()
          |> json(payload)

        {:error, :not_found} ->
          conn
          |> put_public_no_store_headers()
          |> put_status(404)
          |> json(%{detail: "Portfolio workspace not found"})

        {:error, :invalid_portfolio_id} ->
          validation_error(
            conn,
            ["path", "portfolio_id"],
            "String should match a supported portfolio id pattern"
          )

        _ ->
          conn
          |> put_public_no_store_headers()
          |> put_status(503)
          |> json(%{detail: "Portfolio workspace storage unavailable"})
      end
    end)
  end

  def update(conn, %{"portfolio_id" => portfolio_id, "workspace" => workspace}) do
    with_csrf(conn, fn user ->
      case PortfolioWorkspaces.put(user.id, portfolio_id, workspace) do
        {:ok, payload} ->
          conn
          |> put_public_no_store_headers()
          |> json(payload)

        {:error, :invalid_portfolio_id} ->
          validation_error(
            conn,
            ["path", "portfolio_id"],
            "String should match a supported portfolio id pattern"
          )

        {:error, :workspace_too_large} ->
          validation_error(conn, ["body", "workspace"], "Workspace payload is too large")

        {:error, :invalid_workspace} ->
          validation_error(
            conn,
            ["body", "workspace"],
            "Workspace must include version, portfolio, manualInstruments, reviewRequests, and assumptions"
          )

        _ ->
          conn
          |> put_public_no_store_headers()
          |> put_status(503)
          |> json(%{detail: "Portfolio workspace storage unavailable"})
      end
    end)
  end

  def update(conn, _params) do
    validation_error(conn, ["body", "workspace"], "Field required")
  end

  defp with_auth(conn, fun) do
    case Accounts.require_role(conn, @roles) do
      {:ok, user} ->
        fun.(user)

      {:error, :insufficient_role} ->
        conn |> put_status(403) |> json(%{detail: "Insufficient role"})

      _ ->
        conn |> put_status(401) |> json(%{detail: "Not authenticated"})
    end
  end

  defp with_csrf(conn, fun) do
    case Accounts.require_csrf(conn, @roles) do
      {:ok, user} ->
        fun.(user)

      {:error, :invalid_csrf} ->
        conn |> put_status(403) |> json(%{detail: "Invalid CSRF token"})

      {:error, :insufficient_role} ->
        conn |> put_status(403) |> json(%{detail: "Insufficient role"})

      _ ->
        conn |> put_status(401) |> json(%{detail: "Not authenticated"})
    end
  end

  defp validation_error(conn, loc, message) do
    conn
    |> put_public_no_store_headers()
    |> put_status(422)
    |> json(%{detail: [%{loc: loc, msg: message, type: "value_error"}]})
  end

  defp put_public_no_store_headers(conn) do
    conn
    |> put_resp_header("cache-control", "no-store")
    |> put_resp_header("x-content-type-options", "nosniff")
  end
end
