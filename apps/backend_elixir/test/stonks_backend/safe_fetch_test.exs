defmodule StonksBackend.SafeFetchTest do
  use ExUnit.Case, async: true

  alias StonksBackend.SafeFetch

  test "fetch_url returns SafeFetch metadata without raw html" do
    request_fun = fn url, opts ->
      assert url == "https://example.com/story"
      assert opts[:redirect] == false

      {:ok,
       %{
         status: 200,
         headers: %{"content-type" => ["text/html; charset=utf-8"]},
         body: """
         <html>
           <head>
             <meta property="og:title" content="Example OG Title">
             <title>Fallback</title>
           </head>
           <body>
             <h1>Visible Headline</h1>
             <script>secret()</script>
             <p>Useful paragraph.</p>
           </body>
         </html>
         """
       }}
    end

    resolver = fn "example.com", 443 -> {:ok, [{93, 184, 216, 34}]} end

    assert {:ok, payload} =
             SafeFetch.fetch_url("https://example.com/story",
               request_fun: request_fun,
               resolver: resolver,
               max_bytes: 10_000
             )

    assert payload["final_url"] == "https://example.com/story"
    assert payload["status_code"] == 200
    assert payload["title"] == "Example OG Title"
    assert payload["text"] =~ "Visible Headline"
    assert payload["text"] =~ "Useful paragraph"
    refute payload["text"] =~ "secret"
    assert payload["raw_html_returned"] == false
    assert String.starts_with?(payload["content_hash"], "sha256:")
    assert payload["resolved_ips"] == ["93.184.216.34"]
  end

  test "fetch_url blocks private resolved IPs before request" do
    parent = self()
    request_fun = fn _, _ -> send(parent, :request_called) end
    resolver = fn "127.0.0.1", 80 -> {:ok, [{127, 0, 0, 1}]} end

    assert {:error, {:safe_fetch_denied, 400, detail}} =
             SafeFetch.fetch_url("http://127.0.0.1/",
               request_fun: request_fun,
               resolver: resolver
             )

    assert detail =~ "blocked"
    refute_received :request_called
  end

  test "fetch_url revalidates redirects and preserves final URL" do
    request_fun = fn
      "https://example.com/start", _opts ->
        {:ok, %{status: 302, headers: %{"location" => ["/final"]}, body: ""}}

      "https://example.com/final", _opts ->
        {:ok, %{status: 200, headers: %{"content-type" => ["text/plain"]}, body: "done"}}
    end

    resolver = fn "example.com", 443 -> {:ok, [{93, 184, 216, 34}]} end

    assert {:ok, payload} =
             SafeFetch.fetch_url("https://example.com/start",
               request_fun: request_fun,
               resolver: resolver
             )

    assert payload["final_url"] == "https://example.com/final"
    assert payload["text"] == "done"
  end

  test "fetch_url rejects oversized responses" do
    request_fun = fn _, _ ->
      {:ok, %{status: 200, headers: %{"content-type" => ["text/plain"]}, body: "abcdef"}}
    end

    resolver = fn "example.com", 443 -> {:ok, [{93, 184, 216, 34}]} end

    assert {:error, {:safe_fetch_denied, 400, "Response exceeded byte cap"}} =
             SafeFetch.fetch_url("https://example.com/story",
               request_fun: request_fun,
               resolver: resolver,
               max_bytes: 5
             )
  end
end
