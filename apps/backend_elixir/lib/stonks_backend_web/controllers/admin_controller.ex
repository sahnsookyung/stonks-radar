defmodule StonksBackendWeb.AdminController do
  use StonksBackendWeb, :controller

  alias StonksBackend.{Accounts, Audit, Instruments, Jobs, Providers, Snapshots, Sources, Sql}

  @viewer_roles ["owner", "admin", "editor", "viewer"]
  @editor_roles ["owner", "admin", "editor"]
  @admin_roles ["owner", "admin"]

  def dashboard(conn, _params) do
    with_auth(conn, @viewer_roles, fn user ->
      payload = %{
        user: %{email: user.email, role: user.role},
        metrics: %{
          queued_jobs:
            Sql.scalar(
              "select count(*) from oban_jobs where state in ('available','scheduled')",
              [],
              0
            ),
          dead_letter_jobs:
            Sql.scalar(
              "select count(*) from oban_jobs where state in ('discarded','cancelled')",
              [],
              0
            ),
          pending_facts:
            Sql.scalar(
              "select count(*) from source_fact where review_status = 'candidate'",
              [],
              0
            ),
          candidate_events:
            Sql.scalar("select count(*) from geo_event where review_status = 'candidate'", [], 0),
          stale_translations:
            Sql.scalar("select count(*) from content_translation where stale = true", [], 0),
          published_snapshots:
            Sql.scalar(
              "select count(*) from publication_snapshot where publication_status = 'published'",
              [],
              0
            ),
          disk_watermark: "unknown_until_monitor_runs",
          snapshot_storage_status: "local_oci"
        },
        provider_budgets: Providers.budgets(),
        dead_letter_jobs: Jobs.admin_status(),
        source_health:
          Sql.all(
            "select source_key, status, status_code, response_ms, last_checked_at, last_error from source_health_status order by source_key"
          ),
        candidate_facts:
          Sql.all(
            "select id, fact_type, predicate, confidence, extraction_source, created_at from source_fact where review_status = 'candidate' order by created_at desc limit 20"
          ),
        candidate_events:
          Sql.all(
            "select id, event_key, event_type, severity, source_strength, review_status, discovered_at from geo_event where review_status = 'candidate' order by discovered_at desc limit 20"
          ),
        snapshot_candidates: Snapshots.list_candidates()
      }

      json(conn, payload)
    end)
  end

  def provider_budgets(conn, _params),
    do: with_auth(conn, @viewer_roles, fn _ -> json(conn, %{items: Providers.budgets()}) end)

  def kill_switch(conn, %{"budget_id" => id, "enabled" => enabled}) do
    with_csrf(conn, @admin_roles, fn user ->
      Providers.set_kill_switch(id, enabled)

      Audit.write("provider_budget.kill_switch",
        user: user,
        target_table: "provider_budget",
        target_pk: id,
        after: %{enabled: enabled}
      )

      json(conn, %{status: "ok", enabled: enabled})
    end)
  end

  def sources(conn, _params),
    do: with_auth(conn, @viewer_roles, fn _ -> json(conn, %{items: Sources.sources()}) end)

  def create_source(conn, params) do
    with_csrf(conn, @admin_roles, fn user ->
      id = Sources.create_source(params)

      Audit.write("source.create",
        user: user,
        target_table: "data_source",
        target_pk: to_string(id),
        after: params
      )

      json(conn, %{id: to_string(id)})
    end)
  end

  def instrument_search(conn, params) do
    with_auth(conn, @viewer_roles, fn _ ->
      query = String.trim(params["q"] || "A")
      json(conn, Instruments.search(query, limit: 25))
    end)
  end

  def instrument_review_requests(conn, _params) do
    with_auth(conn, @viewer_roles, fn _ ->
      rows = Sql.all("select * from instrument_review_request order by created_at desc limit 200")
      json(conn, %{items: rows})
    end)
  end

  def update_instrument_review_request(conn, %{"request_id" => id, "status" => status} = params) do
    with_csrf(conn, @editor_roles, fn user ->
      if status in ["queued", "in_review", "resolved", "closed", "rejected"] do
        Sql.execute(
          "update instrument_review_request set status = $1, admin_notes = $2, updated_at = now() where id = $3",
          [
            status,
            params["admin_notes"],
            id
          ]
        )

        Audit.write("instrument_review_request.update",
          user: user,
          target_table: "instrument_review_request",
          target_pk: id,
          after: params
        )

        json(conn, %{status: "ok"})
      else
        conn |> put_status(400) |> json(%{detail: "Invalid review request status"})
      end
    end)
  end

  def instrument_detail(conn, %{"instrument_id" => id} = params) do
    with_auth(conn, @viewer_roles, fn _ ->
      case Instruments.detail(id, params["listing_id"]) do
        nil -> conn |> put_status(404) |> json(%{detail: "Instrument not found"})
        payload -> json(conn, payload)
      end
    end)
  end

  def refresh_instruments(conn, params) do
    with_csrf(conn, @admin_roles, fn user ->
      {:ok, job_id} =
        Jobs.enqueue("instrument_search_index_update", Map.put(params, "requested_by", user.id),
          priority: if(String.upcase(params["priority"] || "HIGH") == "HIGH", do: 1, else: 5),
          idempotency_key: "#{params["source"]}:#{params["mode"]}"
        )

      json(conn, %{status: "refreshed", job_id: job_id, refresh: %{status: "queued"}})
    end)
  end

  def ingest_url(conn, params),
    do:
      with_csrf(conn, @editor_roles, fn user ->
        case Sources.ingest_url(params) do
          {:ok, document_id} ->
            Audit.write("source_document.ingest_url",
              user: user,
              target_table: "source_document",
              target_pk: document_id,
              after: %{url: params["url"], source_key: params["source_key"]}
            )

            json(conn, %{id: document_id})

          {:error, detail} ->
            conn |> put_status(400) |> json(%{detail: detail})
        end
      end)

  def summarize_url(conn, _params),
    do:
      with_csrf(conn, @admin_roles, fn _ ->
        conn |> put_status(403) |> json(%{detail: "Admin URL summaries are disabled"})
      end)

  def ingest_file(conn, _params),
    do:
      with_csrf(conn, @editor_roles, fn _ ->
        json(conn, %{status: "manual_file_ingestion_requires_private_storage_policy"})
      end)

  def source_document(conn, %{"document_id" => id}) do
    with_auth(conn, @viewer_roles, fn _ ->
      case Sources.source_document(id) do
        nil -> conn |> put_status(404) |> json(%{detail: "Document not found"})
        row -> json(conn, row)
      end
    end)
  end

  def review_fact(conn, %{"fact_id" => id} = params) do
    with_csrf(conn, @editor_roles, fn user ->
      Sql.execute(
        "update source_fact set review_status = $1, public_allowed = $2 where id = $3",
        [
          params["decision"],
          params["public_allowed"] || false,
          id
        ]
      )

      Audit.write("source_fact.review",
        user: user,
        target_table: "source_fact",
        target_pk: id,
        after: params
      )

      json(conn, %{status: "ok"})
    end)
  end

  def event_candidates(conn, _params) do
    with_auth(conn, @viewer_roles, fn _ ->
      rows =
        Sql.all(
          "select * from geo_event where review_status = 'candidate' order by discovered_at desc limit 100"
        )

      json(conn, %{items: rows})
    end)
  end

  def review_event(conn, %{"event_id" => id} = params) do
    with_csrf(conn, @editor_roles, fn user ->
      public_status = if params["public_allowed"], do: "public_candidate", else: "not_public"

      Sql.execute("update geo_event set review_status = $1, public_status = $2 where id = $3", [
        params["decision"],
        public_status,
        id
      ])

      Audit.write("geo_event.review",
        user: user,
        target_table: "geo_event",
        target_pk: id,
        after: params
      )

      json(conn, %{status: "ok"})
    end)
  end

  def snapshots_build(conn, _params) do
    with_csrf(conn, @editor_roles, fn user ->
      {:ok, job_id} =
        Jobs.enqueue("snapshot_build", %{"requested_by" => user.id},
          queue: :snapshots,
          priority: 1,
          idempotency_key: "manual_latest"
        )

      json(conn, %{status: "queued", job_id: job_id})
    end)
  end

  def snapshots_candidates(conn, _params),
    do:
      with_auth(conn, @viewer_roles, fn _ -> json(conn, %{items: Snapshots.list_candidates()}) end)

  def snapshots_publish(conn, %{"snapshot_version" => version}) do
    with_csrf(conn, @admin_roles, fn _ ->
      case Snapshots.parse_positive_snapshot_version(version) do
        {:ok, version} ->
          case Snapshots.publish(version) do
            {:ok, result} -> json(conn, result)
            {:error, error} -> conn |> put_status(400) |> json(%{detail: error})
          end

        :error ->
          conn
          |> put_status(400)
          |> json(%{detail: "snapshot_version must be a positive integer"})
      end
    end)
  end

  def snapshots_rollback(conn, %{"snapshot_version" => version}) do
    with_csrf(conn, @admin_roles, fn _ ->
      case Snapshots.parse_positive_snapshot_version(version) do
        {:ok, version} ->
          case Snapshots.rollback(version) do
            {:ok, result} -> json(conn, result)
            {:error, error} -> conn |> put_status(400) |> json(%{detail: error})
          end

        :error ->
          conn
          |> put_status(400)
          |> json(%{detail: "snapshot_version must be a positive integer"})
      end
    end)
  end

  def replay_job(conn, %{"job_id" => id}) do
    with_csrf(conn, @admin_roles, fn _ ->
      case Jobs.replay(id) do
        {:ok, job_id} -> json(conn, %{status: "ok", job_id: job_id})
        {:error, reason} -> conn |> put_status(404) |> json(%{detail: to_string(reason)})
      end
    end)
  end

  def create_correction(conn, params) do
    with_csrf(conn, @editor_roles, fn user ->
      if params["status"] in ["correction", "retraction", "clarification"] do
        id =
          Sql.scalar(
            """
            insert into correction_log(title, summary, status, affected_object_key, published_by)
            values ($1, $2, $3, $4, $5)
            returning id
            """,
            [
              params["title"],
              params["summary"],
              params["status"],
              params["affected_object_key"],
              user.id
            ]
          )

        json(conn, %{id: to_string(id)})
      else
        conn |> put_status(400) |> json(%{detail: "Invalid correction status"})
      end
    end)
  end

  def audit_log(conn, _params) do
    with_auth(conn, @viewer_roles, fn _ ->
      rows =
        Sql.all(
          "select id, actor_role, action, target_table, target_pk, request_id, created_at from audit_log order by created_at desc limit 200"
        )

      json(conn, %{items: rows})
    end)
  end

  def snapshots_build_now_local(conn, params),
    do:
      with_csrf(conn, @editor_roles, fn _ ->
        case Snapshots.build_candidate(params) do
          {:ok, result} ->
            json(conn, result)

          {:error, reason} ->
            conn
            |> put_status(501)
            |> json(%{detail: reason})
        end
      end)

  def snapshots_build_seed_local(conn, _params),
    do:
      with_csrf(conn, @editor_roles, fn _ ->
        {:ok, result} = Snapshots.build_local_seed()
        json(conn, result)
      end)

  defp with_auth(conn, roles, fun) do
    case Accounts.require_role(conn, roles) do
      {:ok, user} ->
        fun.(user)

      {:error, :insufficient_role} ->
        conn |> put_status(403) |> json(%{detail: "Insufficient role"})

      _ ->
        conn |> put_status(401) |> json(%{detail: "Not authenticated"})
    end
  end

  defp with_csrf(conn, roles, fun) do
    case Accounts.require_csrf(conn, roles) do
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
end
