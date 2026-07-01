defmodule StonksBackend.SafeFetch do
  @moduledoc "SSRF-guarded metadata fetch boundary owned by the Elixir backend."

  import Bitwise

  alias StonksBackend.Settings

  @default_timeout_seconds 20
  @default_max_bytes 5_000_000
  @max_redirects 5
  @user_agent "StonksRadarSafeFetch/1.0"

  def fetch_url(url, opts \\ []) do
    request_fun = Keyword.get(opts, :request_fun, &Req.get/2)
    resolver = Keyword.get(opts, :resolver, &resolve_host/2)

    timeout_ms =
      opts
      |> Keyword.get(
        :timeout_seconds,
        Settings.get(:source_fetch_timeout_seconds, @default_timeout_seconds)
      )
      |> normalize_int(@default_timeout_seconds)
      |> max(1)
      |> Kernel.*(1_000)

    max_bytes =
      opts
      |> Keyword.get(:max_bytes, Settings.get(:source_fetch_max_bytes, @default_max_bytes))
      |> normalize_int(@default_max_bytes)
      |> max(1)

    fetch_loop(
      normalize_url(url),
      normalize_url(url),
      request_fun,
      resolver,
      timeout_ms,
      max_bytes,
      MapSet.new(),
      0
    )
  end

  defp fetch_loop(
         "",
         _original_url,
         _request_fun,
         _resolver,
         _timeout_ms,
         _max_bytes,
         _ips,
         _redirects
       ),
       do: {:error, {:safe_fetch_denied, 400, "url is required"}}

  defp fetch_loop(
         current_url,
         original_url,
         request_fun,
         resolver,
         timeout_ms,
         max_bytes,
         resolved_ips,
         redirects
       ) do
    with {:ok, decision_ips} <- assert_url_allowed(current_url, resolver),
         request_ips <- MapSet.union(resolved_ips, MapSet.new(decision_ips)),
         {:ok, response} <- request_url(current_url, request_fun, timeout_ms) do
      case maybe_redirect(response) do
        {:redirect, location} ->
          with {:ok, next_url} <- next_redirect_url(current_url, location, redirects) do
            fetch_loop(
              next_url,
              original_url,
              request_fun,
              resolver,
              timeout_ms,
              max_bytes,
              request_ips,
              redirects + 1
            )
          end

        :not_redirect ->
          with :ok <- ok_status(response),
               {:ok, body} <- capped_body(response.body, max_bytes) do
            {:ok, payload(original_url, current_url, response, body, request_ips)}
          end

        {:error, _reason} = error ->
          error
      end
    end
  end

  defp request_url(url, request_fun, timeout_ms) do
    options = [
      headers: [{"user-agent", @user_agent}],
      redirect: false,
      retry: false,
      receive_timeout: timeout_ms
    ]

    case request_fun.(url, options) do
      {:ok, response} ->
        {:ok, response}

      {:error, exception} ->
        {:error, {:safe_fetch_unavailable, Exception.message(exception)}}

      other ->
        {:error, {:safe_fetch_unavailable, "unexpected fetch response: #{inspect(other)}"}}
    end
  end

  defp maybe_redirect(%{status: status, headers: headers}) when status in 300..399 do
    case header_value(headers, "location") do
      nil ->
        {:error, {:safe_fetch_denied, status, "Redirect response missing Location header"}}

      location ->
        {:redirect, location}
    end
  end

  defp maybe_redirect(_response), do: :not_redirect

  defp next_redirect_url(_current_url, _location, redirects) when redirects + 1 > @max_redirects,
    do: {:error, {:safe_fetch_denied, 400, "Too many redirects"}}

  defp next_redirect_url(current_url, location, _redirects) do
    current_url
    |> URI.merge(location)
    |> URI.to_string()
    |> then(&{:ok, &1})
  rescue
    _ -> {:error, {:safe_fetch_denied, 400, "Invalid redirect URL"}}
  end

  defp ok_status(%{status: status}) when status in 200..299, do: :ok

  defp ok_status(%{status: status}),
    do: {:error, {:safe_fetch_denied, status, "source returned HTTP #{status}"}}

  defp payload(original_url, final_url, response, body, resolved_ips) do
    content_type = header_value(response.headers, "content-type") || ""
    extracted = extract_document(body, content_type)

    %{
      "url" => original_url,
      "final_url" => final_url,
      "resolved_ips" => resolved_ips |> MapSet.to_list() |> Enum.sort(),
      "status_code" => response.status,
      "content_type" => content_type,
      "content_hash" => "sha256:" <> Base.encode16(:crypto.hash(:sha256, body), case: :lower),
      "title" => extracted.title,
      "text" => String.slice(extracted.text || "", 0, 20_000),
      "raw_html_returned" => false
    }
  end

  defp assert_url_allowed(url, resolver) do
    parsed = URI.parse(url)

    cond do
      parsed.scheme not in ["http", "https"] ->
        {:error, {:safe_fetch_denied, 400, "Only http/https protocols are allowed"}}

      is_nil(parsed.host) or String.trim(parsed.host) == "" ->
        {:error, {:safe_fetch_denied, 400, "Hostname is required"}}

      true ->
        port = parsed.port || if(parsed.scheme == "https", do: 443, else: 80)
        validate_resolved_ips(parsed.host, port, resolver)
    end
  end

  defp validate_resolved_ips(host, port, resolver) do
    case resolver.(host, port) do
      {:ok, []} ->
        {:error, {:safe_fetch_denied, 400, "DNS resolution returned no addresses"}}

      {:ok, ips} ->
        normalized_ips = Enum.map(ips, &normalize_ip/1)

        case Enum.find(normalized_ips, &blocked_ip?/1) do
          nil ->
            {:ok, Enum.map(normalized_ips, &ip_to_string/1)}

          ip ->
            {:error,
             {:safe_fetch_denied, 400,
              "Private, link-local, loopback, or metadata IP blocked: #{ip_to_string(ip)}"}}
        end

      {:error, reason} ->
        {:error, {:safe_fetch_denied, 400, "DNS resolution failed: #{inspect(reason)}"}}
    end
  end

  defp resolve_host(host, _port) do
    host = to_charlist(host)

    case :inet.parse_address(host) do
      {:ok, ip} ->
        {:ok, [ip]}

      {:error, _} ->
        ipv4 = inet_getaddrs(host, :inet)
        ipv6 = inet_getaddrs(host, :inet6)

        case Enum.uniq(ipv4 ++ ipv6) do
          [] -> {:error, :nxdomain}
          ips -> {:ok, ips}
        end
    end
  end

  defp inet_getaddrs(host, family) do
    case :inet.getaddrs(host, family) do
      {:ok, ips} -> ips
      {:error, _} -> []
    end
  end

  defp capped_body(body, max_bytes) do
    body = body_to_binary(body)

    if byte_size(body) > max_bytes do
      {:error, {:safe_fetch_denied, 400, "Response exceeded byte cap"}}
    else
      {:ok, body}
    end
  end

  defp body_to_binary(body) when is_binary(body), do: body
  defp body_to_binary(body), do: Jason.encode!(body)

  defp extract_document(body, content_type) do
    if String.contains?(String.downcase(to_string(content_type)), "html") do
      extract_html_document(body)
    else
      %{title: nil, text: String.slice(to_string(body), 0, 20_000)}
    end
  end

  defp extract_html_document(body) do
    with {:ok, document} <- Floki.parse_document(body) do
      scrubbed =
        document
        |> Floki.filter_out("script")
        |> Floki.filter_out("style")
        |> Floki.filter_out("noscript")
        |> Floki.filter_out("svg")

      text_root =
        case Floki.find(scrubbed, "body") do
          [] -> scrubbed
          body_nodes -> body_nodes
        end

      %{
        title: extract_title(document),
        text: text_root |> Floki.text(sep: " ") |> normalize_whitespace()
      }
    else
      _ -> %{title: nil, text: String.slice(to_string(body), 0, 20_000)}
    end
  end

  defp extract_title(document) do
    [
      {"meta[property=\"og:title\"]", :content},
      {"meta[name=\"twitter:title\"]", :content},
      {"title", :text},
      {"h1", :text}
    ]
    |> Enum.find_value(fn {selector, mode} ->
      document
      |> Floki.find(selector)
      |> List.first()
      |> title_value(mode)
    end)
  end

  defp title_value(nil, _mode), do: nil

  defp title_value(node, :content) do
    node
    |> Floki.attribute("content")
    |> List.first()
    |> normalize_title()
  end

  defp title_value(node, :text), do: node |> Floki.text() |> normalize_title()

  defp normalize_title(nil), do: nil

  defp normalize_title(value) do
    value = value |> normalize_whitespace() |> String.slice(0, 500)
    if value == "", do: nil, else: value
  end

  defp normalize_whitespace(value) do
    value
    |> to_string()
    |> String.replace(~r/\s+/, " ")
    |> String.trim()
  end

  defp normalize_url(value), do: value |> to_string() |> String.trim()

  defp header_value(headers, key) when is_map(headers) do
    key = String.downcase(key)

    headers
    |> Enum.find_value(fn {header, value} ->
      if String.downcase(to_string(header)) == key do
        value
        |> List.wrap()
        |> List.first()
        |> to_string()
      end
    end)
  end

  defp header_value(headers, key) when is_list(headers) do
    key = String.downcase(key)

    headers
    |> Enum.find_value(fn {header, value} ->
      if String.downcase(to_string(header)) == key do
        value
        |> List.wrap()
        |> List.first()
        |> to_string()
      end
    end)
  end

  defp header_value(_headers, _key), do: nil

  defp blocked_ip?({0, _, _, _}), do: true
  defp blocked_ip?({10, _, _, _}), do: true
  defp blocked_ip?({127, _, _, _}), do: true
  defp blocked_ip?({169, 254, _, _}), do: true
  defp blocked_ip?({172, second, _, _}) when second in 16..31, do: true
  defp blocked_ip?({192, 168, _, _}), do: true
  defp blocked_ip?({first, _, _, _}) when first >= 224, do: true
  defp blocked_ip?({0, 0, 0, 0, 0, 0, 0, 1}), do: true

  defp blocked_ip?({0, 0, 0, 0, 0, 65_535, high, low}) do
    blocked_ip?({high >>> 8, high &&& 255, low >>> 8, low &&& 255})
  end

  defp blocked_ip?({0, 0, 0, 0, 0, 0, high, low}) when high != 0 or low != 0 do
    blocked_ip?({high >>> 8, high &&& 255, low >>> 8, low &&& 255})
  end

  defp blocked_ip?({first, _, _, _, _, _, _, _}) when (first &&& 0xFE00) == 0xFC00, do: true
  defp blocked_ip?({first, _, _, _, _, _, _, _}) when (first &&& 0xFFC0) == 0xFE80, do: true
  defp blocked_ip?({first, _, _, _, _, _, _, _}) when (first &&& 0xFF00) == 0xFF00, do: true
  defp blocked_ip?(_ip), do: false

  defp normalize_ip(ip) when is_tuple(ip), do: ip

  defp normalize_ip(ip) when is_binary(ip) do
    case :inet.parse_address(to_charlist(ip)) do
      {:ok, parsed} -> parsed
      {:error, _} -> {0, 0, 0, 0}
    end
  end

  defp ip_to_string(ip) do
    ip
    |> :inet.ntoa()
    |> to_string()
  end

  defp normalize_int(value, _default) when is_integer(value), do: value

  defp normalize_int(value, default) when is_binary(value) do
    case Integer.parse(String.trim(value)) do
      {integer, ""} -> integer
      _ -> default
    end
  end

  defp normalize_int(_, default), do: default
end
