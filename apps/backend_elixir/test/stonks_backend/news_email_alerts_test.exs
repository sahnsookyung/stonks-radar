defmodule StonksBackend.News.EmailAlertsTest do
  use ExUnit.Case, async: false

  import Plug.Conn
  import Plug.Test

  alias StonksBackend.News.EmailAlerts

  @secret "email-secret"

  setup do
    settings = Application.get_env(:stonks_backend, :settings, [])

    on_exit(fn ->
      Application.put_env(:stonks_backend, :settings, settings)
    end)

    :ok
  end

  test "verify accepts sha256-prefixed uppercase signatures over the exact body" do
    body = ~s({"subject":"Market move","to":"alerts@example.com"})
    nonce_store = in_memory_nonce_store()
    put_email_settings(news_email_nonce_store: nonce_store)

    headers =
      body
      |> signed_headers(nonce: "prefixed-signature")
      |> Map.update!("x-stonks-email-signature", &("sha256=" <> String.upcase(&1)))

    assert :ok = EmailAlerts.verify(headers, body)
  end

  test "verify rejects replayed signature nonces" do
    body = ~s({"subject":"Market move","to":"alerts@example.com"})
    nonce_store = in_memory_nonce_store()
    put_email_settings(news_email_nonce_store: nonce_store)
    headers = signed_headers(body, nonce: "same-nonce")

    assert :ok = EmailAlerts.verify(headers, body)
    assert {:error, "replayed_signature_nonce"} = EmailAlerts.verify(headers, body)
  end

  test "email alert endpoint verifies the raw body after JSON parsing" do
    body = ~s({"subject":"Market move","to":"alerts@example.com","nested":{"a":1}})
    nonce_store = in_memory_nonce_store()
    put_email_settings(news_email_nonce_store: nonce_store)
    headers = signed_headers(body, nonce: "endpoint-raw-body")

    conn =
      :post
      |> conn("/api/internal/news/email-alerts", body)
      |> put_req_header("accept", "application/json")
      |> put_req_header("content-type", "application/json")
      |> put_signed_headers(headers)
      |> StonksBackendWeb.Endpoint.call([])

    assert conn.status == 200

    assert %{"status" => "accepted", "payload_hash" => payload_hash} =
             Jason.decode!(conn.resp_body)

    assert is_binary(payload_hash)
  end

  defp put_email_settings(extra) do
    settings =
      Application.get_env(:stonks_backend, :settings, [])
      |> Keyword.merge(
        [
          news_email_webhook_secret: @secret,
          news_email_signature_max_skew_seconds: "300"
        ] ++ extra
      )

    Application.put_env(:stonks_backend, :settings, settings)
  end

  defp signed_headers(body, opts) do
    timestamp = Keyword.get(opts, :timestamp, System.system_time(:second))
    nonce = Keyword.fetch!(opts, :nonce)

    signature =
      :crypto.mac(:hmac, :sha256, @secret, "#{timestamp}.#{nonce}." <> body)
      |> Base.encode16(case: :lower)

    %{
      "x-stonks-timestamp" => Integer.to_string(timestamp),
      "x-stonks-nonce" => nonce,
      "x-stonks-email-signature" => signature
    }
  end

  defp put_signed_headers(conn, headers) do
    Enum.reduce(headers, conn, fn {key, value}, conn ->
      put_req_header(conn, key, value)
    end)
  end

  defp in_memory_nonce_store do
    {:ok, agent} = Agent.start(fn -> MapSet.new() end)
    on_exit(fn -> if Process.alive?(agent), do: Agent.stop(agent) end)

    fn nonce ->
      Agent.get_and_update(agent, fn seen ->
        if MapSet.member?(seen, nonce) do
          {{:error, "replayed_signature_nonce"}, seen}
        else
          {:ok, MapSet.put(seen, nonce)}
        end
      end)
    end
  end
end
