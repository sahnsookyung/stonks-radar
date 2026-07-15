defmodule StonksBackend.Sources do
  @moduledoc "Source ingestion/disclosure compatibility over preserved tables."

  alias StonksBackend.{SafeFetch, Settings, Sql}

  @allowed_retention %{
    "official_api" => "structured_fact_only",
    "official_page" => "full_text_open",
    "company_ir" => "excerpt_only",
    "filing" => "full_text_open",
    "rss_metadata" => "metadata_only",
    "public_web_fetch" => "metadata_only",
    "metadata_only" => "metadata_only"
  }
  @legal_use_warning "OGE public financial disclosure reports may not be obtained or used for unlawful purposes, commercial purposes other than news/media dissemination to the public, credit-rating purposes, or solicitation purposes."
  @disclosure_limitations [
    "This is a source-linked public disclosure database, not a copy-trading signal.",
    "OGE data is delayed; Form 278-T may be filed up to 45 days after a transaction.",
    "OGE values are amount ranges, not exact trade sizes.",
    "OGE covers Donald J. Trump, spouse, and dependent-child transactions only where reportable in his filings.",
    "Adult family members are tracked only when they appear in SEC filings or issuer disclosures.",
    "SEC Form 144 is proposed sale intent, not proof the sale occurred.",
    "Schedule 13D/G is large beneficial ownership disclosure, not every trade.",
    "Ticker extraction from PDFs can be wrong; every row links back to the source filing."
  ]
  @public_transaction_min_confidence 0.9

  def sources, do: Sql.all("select * from data_source order by source_key")

  def create_source(payload) do
    Sql.scalar(
      """
      insert into data_source(source_key, display_name, source_type, base_url)
      values ($1, $2, $3, $4)
      returning id
      """,
      [
        payload["source_key"],
        payload["display_name"],
        payload["source_type"],
        payload["base_url"]
      ]
    )
  end

  def source_document(id), do: Sql.one("select * from source_document where id = $1", [id])

  def ingest_url(payload) do
    url = payload |> Map.get("url", "") |> to_string() |> String.trim()
    source_key = payload |> Map.get("source_key") |> normalize_blank()

    if url == "" do
      {:error, "url is required"}
    else
      with {:ok, fetched} <- SafeFetch.fetch_url(url),
           {:ok, document_id} <- persist_fetched_source_document(url, source_key, fetched) do
        {:ok, document_id}
      else
        {:error, reason} -> {:error, ingest_error(reason)}
      end
    end
  end

  def ingest_disclosures(payload) do
    include_sec = Map.get(payload, "include_sec", true)
    include_oge = Map.get(payload, "include_oge", true)

    sec_result =
      if include_sec,
        do: ingest_sec_disclosure_metadata(payload),
        else: %{status: "skipped", filings: 0}

    oge_result =
      if include_oge,
        do: record_oge_disclosure_gap(),
        else: %{status: "skipped", filings: 0}

    {:ok,
     %{
       status: disclosure_ingest_status(sec_result, oge_result),
       sec: sec_result,
       oge: oge_result,
       payload: payload,
       elixir_component: "disclosure_metadata_ingest"
     }}
  end

  def persist_metadata_documents(source_key, documents) when is_list(documents) do
    source_id = ensure_metadata_source(source_key)
    ingestion_run_id = ingestion_run_id(source_key)

    persisted =
      documents
      |> Enum.map(&persist_metadata_document(source_id, source_key, &1, ingestion_run_id))
      |> Enum.count(& &1)

    %{documents: persisted}
  end

  def metadata_dedupe_key(document) when is_map(document) do
    case canonical_metadata_url(document) do
      "" -> document["dedupe_key"] || "news:metadata:" <> hash_document(document)
      url -> "news:url:" <> sha256(url)
    end
  end

  defp persist_metadata_document(source_id, source_key, document, ingestion_run_id) do
    document =
      document
      |> ensure_metadata_map()
      |> put_in(["metadata", "ingestion_run_id"], ingestion_run_id)
      |> put_in(["metadata", "release_id"], release_id())
      |> put_in(["metadata", "source_policy_version"], source_policy_version(source_key))
      |> Map.put("ingestion_run_id", ingestion_run_id)
      |> Map.put("release_id", release_id())
      |> Map.put("source_policy_version", source_policy_version(source_key))

    document_id =
      Sql.scalar(
        """
        insert into source_document(
          source_id, title, original_url, canonical_url, publisher, acquisition_mode,
          acquisition_stack, retention_class, fetched_at, content_hash,
          source_published_at, language, dedupe_key, legal_risk_level, review_required,
          downstream_ai_allowed, public_allowed, status, metadata
        )
        values (
          $1, $2, $3, $4, $5, 'news_metadata',
          'adapter_metadata', 'metadata_only', now(), $6,
          $7::text::timestamptz, $8, $9, 'medium', true,
          'extract_only', false, 'discovered', $10::text::jsonb
        )
        on conflict (dedupe_key) where dedupe_key is not null do update
        set title = excluded.title,
            canonical_url = excluded.canonical_url,
            publisher = excluded.publisher,
            source_published_at = excluded.source_published_at,
            language = excluded.language,
            content_hash = excluded.content_hash,
            metadata = source_document.metadata || excluded.metadata,
            updated_at = now()
        returning id
        """,
        [
          source_id,
          document["title"],
          document["url"],
          document["canonical_url"] || document["url"],
          host(document["canonical_url"] || document["url"]) || source_key,
          document["content_hash"] || hash_document(document),
          document["published_at"],
          document["language"] || "en",
          metadata_dedupe_key(document),
          Jason.encode!(document)
        ]
      )

    not is_nil(document_id)
  end

  defp ensure_metadata_map(document) do
    metadata =
      case document["metadata"] do
        %{} = metadata -> metadata
        _ -> %{}
      end

    Map.put(document, "metadata", metadata)
  end

  defp ingestion_run_id(source_key) do
    timestamp = DateTime.utc_now() |> DateTime.truncate(:second) |> DateTime.to_iso8601()
    "ingestion:#{source_key}:#{timestamp}:#{System.unique_integer([:positive])}"
  end

  defp release_id do
    System.get_env("STONKS_RELEASE_ID") ||
      System.get_env("GITHUB_SHA") ||
      "local"
  end

  defp source_policy_version(_source_key), do: 1

  defp canonical_metadata_url(document) do
    (document["canonical_url"] || document["url"] || "")
    |> to_string()
    |> normalize_canonical_url()
  end

  defp normalize_canonical_url(url) do
    uri = URI.parse(String.trim(url))

    if uri.scheme in ["http", "https"] and is_binary(uri.host) do
      query = normalize_query(uri.query)

      %URI{
        uri
        | scheme: String.downcase(uri.scheme),
          host: String.downcase(uri.host),
          path: normalize_path(uri.path),
          query: query,
          fragment: nil
      }
      |> URI.to_string()
    else
      ""
    end
  rescue
    _ -> ""
  end

  defp normalize_path(nil), do: "/"

  defp normalize_path(path) do
    path =
      path
      |> String.replace(~r{/+}, "/")
      |> String.replace(~r{/(amp|mobile)/?$}i, "")

    if path == "", do: "/", else: path
  end

  defp normalize_query(nil), do: nil
  defp normalize_query(""), do: nil

  defp normalize_query(query) do
    query
    |> URI.decode_query()
    |> Enum.reject(fn {key, _value} ->
      key = String.downcase(to_string(key))
      String.starts_with?(key, "utm_") or key in ["fbclid", "gclid", "cmpid"]
    end)
    |> Enum.sort_by(fn {key, value} -> {to_string(key), to_string(value)} end)
    |> case do
      [] -> nil
      params -> URI.encode_query(params)
    end
  rescue
    _ -> nil
  end

  defp ensure_metadata_source(source_key) do
    Sql.scalar("select id from data_source where source_key = $1", [source_key]) ||
      Sql.scalar(
        """
        insert into data_source(source_key, display_name, source_type, base_url)
        values ($1, $2, $3, $4)
        on conflict (source_key) do update set source_type = excluded.source_type
        returning id
        """,
        [
          source_key,
          display_source_key(source_key),
          metadata_source_type(source_key),
          metadata_source_base_url(source_key)
        ]
      )
  end

  defp ingest_sec_disclosure_metadata(payload) do
    limit =
      payload
      |> Map.get("filing_limit", Settings.get(:trump_disclosure_sec_filing_limit, 50))
      |> parse_int(50)
      |> max(1)
      |> min(250)

    people =
      watched_people()
      |> Enum.filter(&(not Enum.empty?(List.wrap(&1["sec_ciks"]))))

    rows =
      people
      |> Enum.flat_map(&fetch_person_sec_filings(&1, limit))
      |> Enum.take(limit)

    %{
      status: if(rows == [], do: "empty", else: "ready"),
      filings: length(rows),
      people: length(people),
      limit: limit,
      source: "SEC"
    }
  end

  defp fetch_person_sec_filings(person, limit) do
    person["sec_ciks"]
    |> List.wrap()
    |> Enum.flat_map(fn cik ->
      with {:ok, payload} <- fetch_sec_submissions(cik),
           recent when is_map(recent) <- get_in(payload, ["filings", "recent"]) do
        parse_sec_submission_filings(person, cik, payload, recent, limit)
      else
        _ -> []
      end
    end)
  end

  defp fetch_sec_submissions(cik) do
    cik_digits =
      cik
      |> to_string()
      |> String.replace(~r/\D/, "")

    if cik_digits == "" do
      {:error, :sec_cik_required}
    else
      fetch_sec_submissions_url(
        "https://data.sec.gov/submissions/CIK#{String.pad_leading(cik_digits, 10, "0")}.json"
      )
    end
  end

  defp fetch_sec_submissions_url(url) do
    case Req.get(url,
           headers: [
             {"accept", "application/json"},
             {"user-agent",
              Settings.get(:sec_user_agent, "StonksRadar/1.0 research contact=admin@example.com")}
           ],
           receive_timeout: source_timeout_ms()
         ) do
      {:ok, %{status: status, body: body}} when status in 200..299 and is_map(body) ->
        {:ok, body}

      {:ok, %{status: status, body: body}} when status in 200..299 ->
        case Jason.decode(to_string(body)) do
          {:ok, decoded} when is_map(decoded) -> {:ok, decoded}
          _ -> {:error, :invalid_sec_response}
        end

      {:ok, %{status: status}} ->
        {:error, {:sec_status, status}}

      {:error, reason} ->
        {:error, reason}
    end
  end

  defp parse_sec_submission_filings(person, cik, payload, recent, limit) do
    accessions = Map.get(recent, "accessionNumber", [])
    forms = Map.get(recent, "form", [])
    filing_dates = Map.get(recent, "filingDate", [])
    report_dates = Map.get(recent, "reportDate", [])
    primary_documents = Map.get(recent, "primaryDocument", [])
    descriptions = Map.get(recent, "primaryDocDescription", [])
    entity_name = payload["name"] || person["canonical_name"]
    ticker = person["tickers"] |> List.wrap() |> List.first()

    accessions
    |> Enum.with_index()
    |> Enum.flat_map(fn {accession, index} ->
      form = sec_array_value(forms, index) |> String.upcase()
      primary_document = sec_array_value(primary_documents, index)
      url = sec_filing_url(cik, accession, primary_document)

      cond do
        not sec_disclosure_form?(form) ->
          []

        url == nil ->
          []

        true ->
          row = %{
            source: "SEC",
            form_type: form,
            filer_name: person["canonical_name"],
            issuer_name: entity_name,
            ticker: ticker,
            cik: cik |> to_string() |> String.replace(~r/\D/, ""),
            accession_number: to_string(accession),
            doc_date:
              first_present(
                sec_array_value(report_dates, index),
                sec_array_value(filing_dates, index)
              ),
            filed_at: sec_filed_at(sec_array_value(filing_dates, index)),
            source_url: url,
            sha256: "sha256:" <> sha256(url),
            raw_metadata: %{
              "description" => sec_array_value(descriptions, index),
              "primary_document" => primary_document,
              "sec_company_name" => payload["name"]
            },
            parse_status: "pending"
          }

          [upsert_source_filing(row)]
      end
    end)
    |> Enum.reject(&is_nil/1)
    |> Enum.take(limit)
  end

  defp upsert_source_filing(row) do
    Sql.scalar(
      """
      insert into source_filings(
        source, form_type, filer_name, issuer_name, ticker, cik, accession_number,
        doc_date, filed_at, source_url, local_path, sha256, raw_metadata, parse_status
      )
      values (
        $1, $2, $3, $4, $5, $6, $7,
        cast($8 as date), cast($9 as timestamptz), $10, null, $11, $12::text::jsonb, $13
      )
      on conflict (source, sha256) do update
      set form_type = excluded.form_type,
          filer_name = excluded.filer_name,
          issuer_name = excluded.issuer_name,
          ticker = excluded.ticker,
          cik = excluded.cik,
          accession_number = excluded.accession_number,
          doc_date = excluded.doc_date,
          filed_at = excluded.filed_at,
          source_url = excluded.source_url,
          raw_metadata = excluded.raw_metadata,
          parse_status = excluded.parse_status
      returning id
      """,
      [
        row.source,
        row.form_type,
        row.filer_name,
        row.issuer_name,
        row.ticker,
        row.cik,
        row.accession_number,
        row.doc_date,
        row.filed_at,
        row.source_url,
        row.sha256,
        Jason.encode!(row.raw_metadata),
        row.parse_status
      ]
    )
  end

  defp record_oge_disclosure_gap do
    details = %{
      elixir_component: "disclosure_metadata_ingest",
      coverage_status: "coverage_gap",
      reason:
        "OGE PDF discovery and parsing are not yet ported to the Elixir disclosure ingester."
    }

    try do
      Sql.execute(
        """
        insert into source_health_status(source_key, status, last_checked_at, details)
        values ('oge_disclosures', 'degraded', now(), $1::text::jsonb)
        on conflict (source_key) do update
        set status = excluded.status,
            last_checked_at = excluded.last_checked_at,
            details = excluded.details
        """,
        [Jason.encode!(details)]
      )
    rescue
      _ -> :ok
    end

    %{
      status: "coverage_gap",
      filings: 0,
      source: "OGE",
      reason: details.reason
    }
  end

  defp disclosure_ingest_status(%{status: "ready"}, _oge), do: "ready"
  defp disclosure_ingest_status(_sec, %{status: "ready"}), do: "ready"
  defp disclosure_ingest_status(%{status: "empty"}, %{status: "skipped"}), do: "empty"

  defp disclosure_ingest_status(%{status: "skipped"}, %{status: "coverage_gap"}),
    do: "coverage_gap"

  defp disclosure_ingest_status(_sec, _oge), do: "partial"

  defp sec_disclosure_form?(form) do
    normalized = form |> to_string() |> String.upcase()

    normalized in ["4", "144", "8-K", "6-K"] or
      String.starts_with?(normalized, "SC 13D") or
      String.starts_with?(normalized, "SC 13G")
  end

  defp sec_array_value(values, index) when is_list(values) do
    values
    |> Enum.at(index, "")
    |> to_string()
    |> String.trim()
  end

  defp sec_array_value(_values, _index), do: ""

  defp sec_filing_url(cik, accession, primary_document) do
    cik_digits = cik |> to_string() |> String.replace(~r/\D/, "")
    accession_path = accession |> to_string() |> String.replace("-", "") |> String.trim()
    primary_document = primary_document |> to_string() |> String.trim()

    if cik_digits == "" or accession_path == "" or primary_document == "" do
      nil
    else
      "https://www.sec.gov/Archives/edgar/data/#{String.to_integer(cik_digits)}/#{accession_path}/#{primary_document}"
    end
  end

  defp sec_filed_at(value) do
    value = value |> to_string() |> String.trim()

    if value == "", do: nil, else: "#{value}T00:00:00Z"
  end

  defp first_present(left, right) do
    left = normalize_blank(left)
    if is_nil(left), do: normalize_blank(right), else: left
  end

  defp source_timeout_ms do
    Settings.get(:source_fetch_timeout_seconds, 10)
    |> parse_int(10)
    |> max(1)
    |> Kernel.*(1000)
  end

  defp persist_fetched_source_document(original_url, source_key, fetched) do
    final_url = fetched["final_url"] || original_url
    source_id = source_id_for(source_key, final_url)
    publisher = host(final_url)
    content_type = fetched["content_type"]
    mode = acquisition_mode(final_url, content_type)
    title = title_for(fetched, publisher)
    content_hash = normalize_blank(fetched["content_hash"]) || hash_document(fetched)
    dedupe_key = "url:" <> sha256(final_url)

    document_id =
      Sql.scalar(
        """
        insert into source_document(
          source_id, title, original_url, canonical_url, publisher, acquisition_mode,
          acquisition_stack, retention_class, fetched_at, content_hash, dedupe_key,
          parse_quality, completeness_score, legal_risk_level, review_required,
          downstream_ai_allowed, public_allowed, status, metadata
        )
        values (
          $1, $2, $3, $4, $5, $6,
          'elixir_safe_fetch', $7, now(), $8, $9,
          $10, $11, $12, true,
          'extract_only', false, 'fetched', $13::text::jsonb
        )
        on conflict (dedupe_key) where dedupe_key is not null do update
        set title = excluded.title,
            original_url = excluded.original_url,
            canonical_url = excluded.canonical_url,
            publisher = excluded.publisher,
            acquisition_mode = excluded.acquisition_mode,
            acquisition_stack = excluded.acquisition_stack,
            retention_class = excluded.retention_class,
            fetched_at = excluded.fetched_at,
            content_hash = excluded.content_hash,
            parse_quality = excluded.parse_quality,
            completeness_score = excluded.completeness_score,
            legal_risk_level = excluded.legal_risk_level,
            review_required = excluded.review_required,
            downstream_ai_allowed = excluded.downstream_ai_allowed,
            public_allowed = excluded.public_allowed,
            status = excluded.status,
            metadata = source_document.metadata || excluded.metadata,
            updated_at = now()
        returning id
        """,
        [
          source_id,
          title,
          original_url,
          final_url,
          publisher,
          mode,
          retention_class(mode),
          content_hash,
          dedupe_key,
          parse_quality(content_type),
          1.0,
          legal_risk_level(mode),
          Jason.encode!(%{
            "content_type" => content_type,
            "resolved_ips" => fetched["resolved_ips"] || [],
            "status_code" => fetched["status_code"],
            "title" => normalize_blank(fetched["title"]),
            "raw_retained" => false,
            "text_chars" => String.length(to_string(fetched["text"] || ""))
          })
        ]
      )

    if is_nil(document_id),
      do: {:error, :source_document_insert_failed},
      else: {:ok, to_string(document_id)}
  end

  defp source_id_for(source_key, final_url) do
    cond do
      is_binary(source_key) ->
        Sql.scalar("select id from data_source where source_key = $1", [source_key]) ||
          ensure_manual_source(source_key, final_url)

      true ->
        Sql.scalar(
          "select id from data_source where base_url ilike $1 order by created_at limit 1",
          ["%#{host(final_url)}%"]
        ) || ensure_manual_source("manual_url_ingest", final_url)
    end
  end

  defp ensure_manual_source(source_key, final_url) do
    Sql.scalar(
      """
      insert into data_source(source_key, display_name, source_type, base_url)
      values ($1, $2, 'public_web', $3)
      on conflict (source_key) do update set base_url = coalesce(data_source.base_url, excluded.base_url)
      returning id
      """,
      [source_key, display_source_key(source_key), "#{scheme(final_url)}://#{host(final_url)}"]
    )
  end

  defp acquisition_mode(final_url, content_type) do
    host = host(final_url)

    cond do
      host == "sec.gov" or String.ends_with?(host, ".sec.gov") ->
        "filing"

      String.ends_with?(host, ".gov") ->
        if String.contains?(String.downcase(to_string(content_type)), "html"),
          do: "official_page",
          else: "official_api"

      String.contains?(String.downcase(to_string(content_type)), "xml") ->
        "rss_metadata"

      true ->
        "public_web_fetch"
    end
  end

  defp title_for(fetched, publisher) do
    fetched_title = normalize_blank(fetched["title"])

    text_title =
      fetched["text"]
      |> to_string()
      |> String.split(["\n", "\r", "\t"], trim: true)
      |> Enum.find(&(&1 |> String.trim() |> String.length() >= 8))

    case fetched_title || text_title do
      nil -> if publisher == "", do: "Fetched source document", else: publisher
      title -> title |> String.trim() |> String.slice(0, 500)
    end
  end

  defp retention_class(mode), do: Map.get(@allowed_retention, mode, "metadata_only")

  defp legal_risk_level(mode) when mode in ["official_api", "official_page", "filing"], do: "low"
  defp legal_risk_level(_mode), do: "unknown"

  defp parse_quality(content_type) do
    if String.contains?(String.downcase(to_string(content_type)), "html"), do: 0.7, else: 0.5
  end

  defp display_source_key(source_key) do
    source_key
    |> to_string()
    |> String.replace(["_", "-"], " ")
    |> String.split(" ", trim: true)
    |> Enum.map_join(" ", &String.capitalize/1)
  end

  defp host(url) do
    case URI.parse(to_string(url)) do
      %URI{host: host} when is_binary(host) -> String.downcase(host)
      _ -> ""
    end
  end

  defp scheme(url) do
    case URI.parse(to_string(url)) do
      %URI{scheme: scheme} when scheme in ["http", "https"] -> scheme
      _ -> "https"
    end
  end

  defp ingest_error({:safe_fetch_denied, _status, detail}), do: detail

  defp ingest_error({:safe_fetch_unavailable, detail}),
    do: "SafeFetch unavailable: #{detail}"

  defp ingest_error(reason), do: to_string(reason)

  defp hash_document(document) do
    "sha256:" <>
      (:crypto.hash(:sha256, Jason.encode!(document)) |> Base.encode16(case: :lower))
  end

  defp sha256(value) do
    :crypto.hash(:sha256, to_string(value))
    |> Base.encode16(case: :lower)
  end

  defp metadata_source_type("gdelt"), do: "aggregator"
  defp metadata_source_type("google_news_rss"), do: "rss"
  defp metadata_source_type("federal_reserve"), do: "rss"
  defp metadata_source_type("who"), do: "rss"
  defp metadata_source_type("sec_edgar"), do: "filing"

  defp metadata_source_type(source_key) do
    if String.starts_with?(to_string(source_key), "sec_"), do: "filing", else: "news_metadata"
  end

  defp metadata_source_base_url("gdelt"), do: "https://api.gdeltproject.org"
  defp metadata_source_base_url("google_news_rss"), do: "https://news.google.com/rss"
  defp metadata_source_base_url("federal_reserve"), do: "https://www.federalreserve.gov"
  defp metadata_source_base_url("who"), do: "https://www.who.int"
  defp metadata_source_base_url("sec_edgar"), do: "https://data.sec.gov"

  defp metadata_source_base_url(source_key) do
    if String.starts_with?(to_string(source_key), "sec_"), do: "https://data.sec.gov", else: nil
  end

  defp normalize_blank(value) when is_binary(value) do
    value = String.trim(value)
    if value == "", do: nil, else: value
  end

  defp normalize_blank(_), do: nil

  def filings(params) do
    limit = parse_limit(params["limit"], 100, 250)
    {conditions, values} = disclosure_filters("sf", params, [])
    limit_index = length(values) + 1

    rows =
      Sql.all(
        """
        select sf.id, sf.source, sf.form_type, sf.filer_name, sf.issuer_name,
               sf.ticker, sf.cik, sf.accession_number, sf.doc_date, sf.filed_at,
               sf.source_url, sf.parse_status, sf.created_at,
               (select count(*) from security_transactions st where st.filing_id = sf.id) as transaction_count
        from source_filings sf
        where #{Enum.join(conditions, " and ")}
        order by coalesce(sf.doc_date, cast(sf.created_at as date)) desc, sf.id desc
        limit $#{limit_index}
        """,
        values ++ [limit]
      )

    %{filings: rows, limitations: @disclosure_limitations}
  end

  def transactions(params) do
    limit = parse_limit(params["limit"], 100, 500)

    base_conditions = [
      "coalesce(st.confidence, 0) >= $1",
      "(st.source <> 'OGE' or st.ticker is not null)"
    ]

    base_values = [@public_transaction_min_confidence]
    {conditions, values} = disclosure_filters("st", params, {base_conditions, base_values})
    limit_index = length(values) + 1

    rows =
      Sql.all(
        """
        select st.id, st.source, st.person_name, st.owner_name, st.issuer_name,
               st.ticker, st.cik, st.asset_description, st.transaction_type,
               st.transaction_code, st.transaction_date, st.amount_min, st.amount_max,
               st.shares, st.price, st.direct_or_indirect, st.ownership_nature,
               st.post_transaction_shares, st.is_late, st.source_page, st.confidence,
               sf.source_url, sf.form_type, sf.filed_at, sf.doc_date
        from security_transactions st
        join source_filings sf on sf.id = st.filing_id
        where #{Enum.join(conditions, " and ")}
        order by st.transaction_date desc nulls last, sf.doc_date desc nulls last, st.id desc
        limit $#{limit_index}
        """,
        values ++ [limit]
      )

    %{
      transactions: rows,
      limitations: @disclosure_limitations,
      min_confidence: @public_transaction_min_confidence
    }
  end

  def insiders(ticker, limit) do
    payload =
      transactions(%{
        "ticker" => ticker,
        "source" => "SEC",
        "limit" => limit
      })

    insiders =
      payload.transactions
      |> Enum.reduce(%{}, fn row, owners ->
        owner = row["owner_name"] || row["person_name"] || "Unknown owner"

        current =
          Map.get(owners, owner, %{
            "owner_name" => owner,
            "transactions" => 0,
            "latest_transaction_date" => nil
          })

        latest = latest_date(current["latest_transaction_date"], row["transaction_date"])

        Map.put(owners, owner, %{
          "owner_name" => owner,
          "transactions" => current["transactions"] + 1,
          "latest_transaction_date" => latest
        })
      end)
      |> Map.values()
      |> Enum.sort_by(&{&1["latest_transaction_date"] || "", &1["owner_name"]}, :desc)

    payload
    |> Map.put(:ticker, ticker |> to_string() |> String.upcase())
    |> Map.put(:insiders, insiders)
  end

  def disclosure_summary(limit) do
    limit = parse_limit(limit, 50, 250)

    %{
      legal_use_warning: @legal_use_warning,
      limitations: @disclosure_limitations,
      filings: filings(%{"limit" => limit}).filings,
      transactions: transactions(%{"limit" => limit}).transactions,
      watched_people: watched_people(),
      open_review_items:
        Sql.scalar("select count(*) from parse_review_queue where status = 'open'", [], 0)
    }
  end

  defp disclosure_filters(alias_name, params, initial) when is_map(params) do
    {conditions, values} = normalize_initial_filters(initial)

    {conditions, values}
    |> add_source_filter(alias_name, params["source"])
    |> add_ticker_filter(alias_name, params["ticker"])
    |> add_person_filter(alias_name, params["person"])
  end

  defp disclosure_filters(_alias_name, _params, initial), do: normalize_initial_filters(initial)

  defp normalize_initial_filters([]), do: {["true"], []}
  defp normalize_initial_filters({conditions, values}), do: {conditions, values}

  defp add_source_filter(filters, _alias_name, nil), do: filters
  defp add_source_filter(filters, _alias_name, ""), do: filters

  defp add_source_filter({conditions, values}, alias_name, source) do
    source = source |> to_string() |> String.upcase()
    add_condition({conditions, values}, "#{alias_name}.source = $IDX", source)
  end

  defp add_ticker_filter(filters, _alias_name, nil), do: filters
  defp add_ticker_filter(filters, _alias_name, ""), do: filters

  defp add_ticker_filter({conditions, values}, alias_name, ticker) do
    add_condition(
      {conditions, values},
      "upper(#{alias_name}.ticker) = $IDX",
      ticker |> to_string() |> String.upcase()
    )
  end

  defp add_person_filter(filters, _alias_name, nil), do: filters
  defp add_person_filter(filters, _alias_name, ""), do: filters

  defp add_person_filter({conditions, values}, "sf", person) do
    condition = """
    (
      sf.filer_name ilike $IDX escape '!'
      or exists (
        select 1 from security_transactions st
        where st.filing_id = sf.id
          and (st.person_name ilike $IDX escape '!' or st.owner_name ilike $IDX escape '!')
      )
    )
    """

    add_condition({conditions, values}, condition, "%#{escape_like(person)}%")
  end

  defp add_person_filter({conditions, values}, alias_name, person) do
    add_condition(
      {conditions, values},
      "(#{alias_name}.person_name ilike $IDX escape '!' or #{alias_name}.owner_name ilike $IDX escape '!')",
      "%#{escape_like(person)}%"
    )
  end

  defp add_condition({conditions, values}, condition, value) do
    index = length(values) + 1
    {[String.replace(condition, "$IDX", "$#{index}") | conditions], values ++ [value]}
  end

  defp watched_people do
    Sql.all("""
    select canonical_name, category, aliases, tickers, sec_ciks, oge_names, notes
    from watched_people
    order by
      case category
        when 'donald_trump' then 1
        when 'spouse' then 2
        when 'dependent_child' then 3
        when 'adult_family' then 4
        else 5
      end,
      canonical_name
    """)
  end

  defp latest_date(nil, candidate), do: candidate
  defp latest_date(current, nil), do: current
  defp latest_date(current, candidate) when candidate > current, do: candidate
  defp latest_date(current, _candidate), do: current

  defp parse_limit(value, default, max_value) do
    value
    |> parse_int(default)
    |> max(1)
    |> min(max_value)
  end

  defp parse_int(value, _default) when is_integer(value), do: value

  defp parse_int(value, default) do
    case Integer.parse(to_string(value || default)) do
      {parsed, ""} -> parsed
      _ -> default
    end
  end

  defp escape_like(value) do
    value
    |> to_string()
    |> String.replace("!", "!!")
    |> String.replace("%", "!%")
    |> String.replace("_", "!_")
  end
end
