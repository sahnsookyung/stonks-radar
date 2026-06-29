defmodule StonksBackendWeb.ContractCase do
  @moduledoc """
  DB-free helpers for Phoenix compatibility tests.

  Contract rows should mirror `docs/elixir-backend-compatibility-matrix.md`.
  Keep rows focused on HTTP-observable behavior: status, JSON shape, headers,
  cookies, and cache semantics. Rows that need persisted data should load
  sanitized fixtures or mocks rather than a live database.
  """

  use ExUnit.CaseTemplate

  import ExUnit.Assertions
  import Plug.Conn

  @default_request_headers [
    {"accept", "application/json"},
    {"origin", "http://localhost:5173"}
  ]

  @fixture_root Path.expand("fixtures", __DIR__)

  using do
    quote do
      import StonksBackendWeb.ContractCase
    end
  end

  def assert_contract(row) when is_map(row) do
    conn = call_contract(row)

    assert conn.status == Map.fetch!(row, :status)

    row
    |> Map.get(:json_subset)
    |> then(&assert_json_subset(conn, &1))

    row
    |> Map.get(:json_keys, [])
    |> then(&assert_json_keys(conn, &1))

    row
    |> Map.get(:response_headers, %{})
    |> then(&assert_response_headers(conn, &1))

    row
    |> Map.get(:absent_response_headers, [])
    |> then(&assert_absent_response_headers(conn, &1))

    row
    |> Map.get(:response_cookies)
    |> then(&assert_response_cookies(conn, &1))

    conn
  end

  def call_contract(row) when is_map(row) do
    method = Map.fetch!(row, :method)
    path = Map.fetch!(row, :path)
    body = Map.get(row, :body)
    request_headers = @default_request_headers ++ Map.get(row, :request_headers, [])

    method
    |> build_conn(path, body)
    |> put_request_headers(request_headers)
    |> maybe_put_json_content_type(body)
    |> StonksBackendWeb.Endpoint.call([])
  end

  def json_body(conn), do: Jason.decode!(conn.resp_body)

  def load_fixture(relative_path) do
    fixture_path =
      @fixture_root
      |> Path.join(relative_path)
      |> Path.expand()

    unless String.starts_with?(fixture_path, @fixture_root <> "/") do
      raise ArgumentError, "contract fixtures must stay under #{@fixture_root}"
    end

    fixture_path
    |> File.read!()
    |> Jason.decode!()
  end

  def assert_json_subset(_conn, nil), do: :ok

  def assert_json_subset(conn, expected) when is_map(expected) do
    assert_subset(expected, json_body(conn))
  end

  def assert_json_keys(_conn, []), do: :ok

  def assert_json_keys(conn, keys) when is_list(keys) do
    body = json_body(conn)

    for key <- keys do
      assert Map.has_key?(body, key), "expected JSON response to include key #{inspect(key)}"
    end
  end

  def assert_response_headers(_conn, expected) when expected in [%{}, []], do: :ok

  def assert_response_headers(conn, expected) do
    for {name, expectation} <- expected do
      actual = get_resp_header(conn, name)
      assert actual != [], "expected response header #{name}"
      assert_header_expectation(name, actual, expectation)
    end
  end

  def assert_absent_response_headers(_conn, []), do: :ok

  def assert_absent_response_headers(conn, names) when is_list(names) do
    for name <- names do
      assert get_resp_header(conn, name) == [], "expected response header #{name} to be absent"
    end
  end

  def assert_response_cookies(_conn, nil), do: :ok

  def assert_response_cookies(conn, :none) do
    assert conn.resp_cookies == %{}, "expected no response cookies"
  end

  def assert_response_cookies(conn, expected_names) when is_list(expected_names) do
    for name <- expected_names do
      assert Map.has_key?(conn.resp_cookies, name), "expected response cookie #{name}"
    end
  end

  defp build_conn(method, path, nil), do: Plug.Test.conn(method, path)

  defp build_conn(method, path, body) when is_binary(body), do: Plug.Test.conn(method, path, body)

  defp build_conn(method, path, body) when is_map(body) or is_list(body) do
    Plug.Test.conn(method, path, Jason.encode!(body))
  end

  defp put_request_headers(conn, headers) do
    Enum.reduce(headers, conn, fn {key, value}, acc -> put_req_header(acc, key, value) end)
  end

  defp maybe_put_json_content_type(conn, body) when is_map(body) or is_list(body) do
    put_req_header(conn, "content-type", "application/json")
  end

  defp maybe_put_json_content_type(conn, _body), do: conn

  defp assert_subset(expected, actual) when is_map(expected) and is_map(actual) do
    for {key, expected_value} <- expected do
      assert Map.has_key?(actual, key), "expected JSON object to include key #{inspect(key)}"
      assert_subset(expected_value, Map.fetch!(actual, key))
    end
  end

  defp assert_subset(expected, actual), do: assert(actual == expected)

  defp assert_header_expectation(_name, _actual, :present), do: :ok

  defp assert_header_expectation(name, actual, {:contains, expected}) do
    assert Enum.any?(actual, &String.contains?(&1, expected)),
           "expected response header #{name} to contain #{inspect(expected)}, got #{inspect(actual)}"
  end

  defp assert_header_expectation(name, actual, expected) when is_binary(expected) do
    assert expected in actual,
           "expected response header #{name} to include #{inspect(expected)}, got #{inspect(actual)}"
  end

  defp assert_header_expectation(name, actual, expected) when is_list(expected) do
    assert actual == expected,
           "expected response header #{name} to equal #{inspect(expected)}, got #{inspect(actual)}"
  end
end
