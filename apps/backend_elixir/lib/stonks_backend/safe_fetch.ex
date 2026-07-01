defmodule StonksBackend.SafeFetch do
  @moduledoc "Production fetch boundary. The fetch-sandbox remains authoritative for v1."

  alias StonksBackend.Settings

  @default_timeout_seconds 20

  def fetch_url(url, opts \\ []) do
    with {:ok, endpoint} <- fetch_sandbox_endpoint(),
         {:ok, response} <- request_sandbox(endpoint, url, opts),
         {:ok, payload} <- normalize_payload(response.body) do
      {:ok, payload}
    end
  end

  defp fetch_sandbox_endpoint do
    endpoint =
      Settings.get(:fetch_sandbox_url, "")
      |> to_string()
      |> String.trim()

    if endpoint == "" do
      {:error, :fetch_sandbox_url_not_configured}
    else
      {:ok, endpoint}
    end
  end

  defp request_sandbox(endpoint, url, opts) do
    timeout_seconds =
      opts
      |> Keyword.get(
        :timeout_seconds,
        Settings.get(:source_fetch_timeout_seconds, @default_timeout_seconds)
      )
      |> normalize_int(@default_timeout_seconds)
      |> max(1)

    request =
      Req.new(
        url: endpoint,
        method: :post,
        json: %{url: url},
        receive_timeout: timeout_seconds * 1_000,
        retry: false
      )

    case Req.request(request) do
      {:ok, %{status: status} = response} when status in 200..299 ->
        {:ok, response}

      {:ok, %{body: body, status: status}} ->
        {:error, {:fetch_sandbox_denied, status, detail_from_body(body)}}

      {:error, exception} ->
        {:error, {:fetch_sandbox_unavailable, Exception.message(exception)}}
    end
  end

  defp normalize_payload(body) when is_map(body) do
    required = ["final_url", "content_hash", "text", "status_code"]

    if Enum.all?(required, &Map.has_key?(body, &1)) do
      {:ok, body}
    else
      {:error, :fetch_sandbox_malformed_response}
    end
  end

  defp normalize_payload(_), do: {:error, :fetch_sandbox_malformed_response}

  defp detail_from_body(%{"detail" => detail}), do: to_string(detail)
  defp detail_from_body(body) when is_binary(body), do: body
  defp detail_from_body(_), do: "fetch sandbox request failed"

  defp normalize_int(value, _default) when is_integer(value), do: value

  defp normalize_int(value, default) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp normalize_int(_, default), do: default
end
