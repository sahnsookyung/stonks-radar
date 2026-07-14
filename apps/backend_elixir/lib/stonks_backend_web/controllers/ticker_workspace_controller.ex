defmodule StonksBackendWeb.TickerWorkspaceController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{Accounts, Settings, TickerWorkspaces}

  @roles ~w(owner admin editor viewer member)

  def show(conn, _params) do
    with_auth(conn, fn user ->
      case TickerWorkspaces.get(user.id) do
        {:ok, payload} -> no_store_json(conn, payload)
        _ -> unavailable(conn)
      end
    end)
  end

  def update(conn, %{"workspace" => workspace, "revision" => revision}) do
    with_csrf(conn, fn user ->
      user.id
      |> TickerWorkspaces.put(workspace, revision)
      |> respond_write(conn)
    end)
  end

  def update(conn, _params), do: validation_error(conn, "workspace and revision are required")

  def merge(conn, %{"workspace" => workspace, "revision" => revision}) do
    with_csrf(conn, fn user ->
      user.id
      |> TickerWorkspaces.merge(workspace, revision)
      |> respond_write(conn)
    end)
  end

  def merge(conn, _params), do: validation_error(conn, "workspace and revision are required")

  defp respond_write({:ok, payload}, conn), do: no_store_json(conn, payload)

  defp respond_write({:error, :conflict, current}, conn) do
    conn
    |> put_status(409)
    |> no_store_json(%{detail: "Workspace revision conflict", current: current})
  end

  defp respond_write({:error, reason}, conn)
       when reason in [
              :invalid_workspace,
              :invalid_revision,
              :invalid_symbol,
              :invalid_notes,
              :invalid_comparisons,
              :watchlist_limit,
              :notes_limit,
              :comparisons_limit,
              :workspace_too_large
            ],
       do: validation_error(conn, Atom.to_string(reason))

  defp respond_write(_error, conn), do: unavailable(conn)

  defp with_auth(conn, fun) do
    if Settings.ticker_member_features_enabled?() do
      case Accounts.require_role(conn, @roles) do
        {:ok, user} ->
          fun.(user)

        {:error, :insufficient_role} ->
          conn |> put_status(403) |> no_store_json(%{detail: "Insufficient role"})

        _ ->
          conn |> put_status(401) |> no_store_json(%{detail: "Not authenticated"})
      end
    else
      feature_disabled(conn)
    end
  end

  defp with_csrf(conn, fun) do
    if Settings.ticker_member_features_enabled?() do
      case Accounts.require_csrf(conn, @roles) do
        {:ok, user} ->
          fun.(user)

        {:error, :invalid_csrf} ->
          conn |> put_status(403) |> no_store_json(%{detail: "Invalid CSRF token"})

        {:error, :insufficient_role} ->
          conn |> put_status(403) |> no_store_json(%{detail: "Insufficient role"})

        _ ->
          conn |> put_status(401) |> no_store_json(%{detail: "Not authenticated"})
      end
    else
      feature_disabled(conn)
    end
  end

  defp feature_disabled(conn),
    do: conn |> put_status(404) |> no_store_json(%{detail: "Ticker member features disabled"})

  defp validation_error(conn, message) do
    conn
    |> put_status(422)
    |> no_store_json(%{
      detail: [%{loc: ["body", "workspace"], msg: message, type: "value_error"}]
    })
  end

  defp unavailable(conn),
    do:
      conn |> put_status(503) |> no_store_json(%{detail: "Ticker workspace storage unavailable"})

  defp no_store_json(conn, payload) do
    conn
    |> put_resp_header("cache-control", "no-store")
    |> put_resp_header("x-content-type-options", "nosniff")
    |> json(payload)
  end
end
