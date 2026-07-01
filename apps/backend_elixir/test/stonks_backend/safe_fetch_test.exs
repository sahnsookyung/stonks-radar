defmodule StonksBackend.SafeFetchTest do
  use ExUnit.Case, async: false

  alias StonksBackend.SafeFetch

  setup do
    original = Application.get_env(:stonks_backend, :settings)

    on_exit(fn ->
      if is_nil(original) do
        Application.delete_env(:stonks_backend, :settings)
      else
        Application.put_env(:stonks_backend, :settings, original)
      end
    end)
  end

  test "fetch_url delegates to the configured fetch-sandbox endpoint" do
    bypass = Bypass.open()

    Application.put_env(:stonks_backend, :settings,
      fetch_sandbox_url: "http://localhost:#{bypass.port}/fetch",
      source_fetch_timeout_seconds: "2"
    )

    Bypass.expect_once(bypass, "POST", "/fetch", fn conn ->
      {:ok, body, conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"url" => "https://example.com/story"}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.resp(
        200,
        Jason.encode!(%{
          final_url: "https://example.com/story",
          resolved_ips: ["93.184.216.34"],
          status_code: 200,
          content_type: "text/html",
          content_hash: "sha256:test",
          title: "Example Story Title",
          text: "Example Story",
          raw_html_returned: false
        })
      )
    end)

    assert {:ok, payload} = SafeFetch.fetch_url("https://example.com/story")
    assert payload["title"] == "Example Story Title"
    assert payload["text"] == "Example Story"
    assert payload["raw_html_returned"] == false
  end

  test "fetch_url returns sandbox denial details" do
    bypass = Bypass.open()

    Application.put_env(:stonks_backend, :settings,
      fetch_sandbox_url: "http://localhost:#{bypass.port}/fetch",
      source_fetch_timeout_seconds: "2"
    )

    Bypass.expect_once(bypass, "POST", "/fetch", fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.resp(400, Jason.encode!(%{detail: "Private IP blocked"}))
    end)

    assert {:error, {:fetch_sandbox_denied, 400, "Private IP blocked"}} =
             SafeFetch.fetch_url("http://127.0.0.1/")
  end
end
