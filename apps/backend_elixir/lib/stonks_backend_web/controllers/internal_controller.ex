defmodule StonksBackendWeb.InternalController do
  use StonksBackendWeb, :controller

  alias StonksBackend.News.EmailAlerts

  def receive_news_email_alert(conn, params) do
    body = StonksBackendWeb.Endpoint.raw_body(conn)

    case EmailAlerts.verify(Map.new(conn.req_headers), body) do
      :ok ->
        json(conn, EmailAlerts.ingest(params))

      {:error, reason} ->
        conn |> put_status(email_error_status(reason)) |> json(%{detail: reason})
    end
  end

  defp email_error_status("email_webhook_disabled"), do: 503

  defp email_error_status(reason)
       when reason in [
              "invalid_signature",
              "missing_signature_headers",
              "stale_signature",
              "replayed_signature_nonce"
            ],
       do: 401

  defp email_error_status("recipient_not_allowed"), do: 403
  defp email_error_status("email_webhook_nonce_store_unavailable"), do: 503
  defp email_error_status(_), do: 400
end
