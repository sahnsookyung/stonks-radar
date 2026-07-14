defmodule StonksBackend.TickerNotifications do
  @moduledoc "Opt-in localized alert email delivery and unsubscribe handling."

  import Swoosh.Email

  alias StonksBackend.{Mailer, Settings, Sql}

  def preferences(user_id) do
    row =
      Sql.one(
        "select locale, email_opt_in, unsubscribed_at, updated_at from user_notification_preference where user_id = $1",
        [user_id]
      )

    {:ok,
     row ||
       %{"locale" => "en", "email_opt_in" => false, "unsubscribed_at" => nil, "updated_at" => nil}}
  rescue
    _ -> {:error, :storage_unavailable}
  end

  def update_preferences(user_id, attrs) do
    locale = if to_string(attrs["locale"] || attrs[:locale]) == "ko", do: "ko", else: "en"
    opt_in = attrs["email_opt_in"] in [true, "true", 1, "1"] or attrs[:email_opt_in] == true

    row =
      Sql.one(
        """
        insert into user_notification_preference(
          user_id, locale, email_opt_in, unsubscribed_at, unsubscribe_token_hash
        )
        values ($1, $2, $3, null, null)
        on conflict (user_id) do update set
          locale = excluded.locale,
          email_opt_in = excluded.email_opt_in,
          unsubscribed_at = case when excluded.email_opt_in then null else user_notification_preference.unsubscribed_at end,
          updated_at = now()
        returning locale, email_opt_in, unsubscribed_at, updated_at
        """,
        [user_id, locale, opt_in]
      )

    if row, do: {:ok, row}, else: {:error, :storage_unavailable}
  end

  def unsubscribe(token) when is_binary(token) and byte_size(token) <= 256 do
    with {:ok, user_id} <-
           Phoenix.Token.verify(StonksBackendWeb.Endpoint, "ticker-alert-unsubscribe", token,
             max_age: 365 * 24 * 60 * 60
           ),
         row when not is_nil(row) <-
           Sql.one(
             """
             update user_notification_preference
             set email_opt_in = false, unsubscribed_at = now(), updated_at = now()
             where user_id = $1
             returning user_id
             """,
             [user_id]
           ) do
      :ok
    else
      _ -> {:error, :not_found}
    end
  end

  def unsubscribe(_token), do: {:error, :not_found}

  def deliver_event(%{"event_id" => event_id}), do: deliver_event(event_id)

  def deliver_event(event_id) do
    if not Settings.truthy?(Settings.get(:ticker_email_enabled, "false")) do
      {:ok, %{status: "disabled"}}
    else
      deliver_enabled_event(event_id)
    end
  end

  defp deliver_enabled_event(event_id) do
    row =
      Sql.one(
        """
        select e.id, e.user_id, e.reason, e.source_at, e.delivery_status,
               r.symbol, u.email, p.locale, p.email_opt_in, p.unsubscribed_at
        from ticker_alert_event e
        join ticker_alert_rule r on r.id = e.rule_id
        join app_user u on u.id = e.user_id
        left join user_notification_preference p on p.user_id = e.user_id
        where e.id = $1
        """,
        [event_id]
      )

    cond do
      is_nil(row) ->
        {:discard, "alert event not found"}

      row["delivery_status"] == "email_accepted" ->
        {:ok, %{status: "already_accepted"}}

      row["email_opt_in"] != true or not is_nil(row["unsubscribed_at"]) ->
        {:ok, %{status: "not_opted_in"}}

      true ->
        send_alert_email(row)
    end
  end

  defp send_alert_email(row) do
    locale = if row["locale"] == "ko", do: "ko", else: "en"
    base = Settings.get(:public_base_url, "http://localhost:5173") |> String.trim_trailing("/")

    unsubscribe_token =
      Phoenix.Token.sign(
        StonksBackendWeb.Endpoint,
        "ticker-alert-unsubscribe",
        to_string(row["user_id"])
      )

    unsubscribe_url =
      "#{base}/api/public/notifications/unsubscribe?#{URI.encode_query(%{token: unsubscribe_token})}"

    subject = if locale == "ko", do: "#{row["symbol"]} 알림", else: "#{row["symbol"]} alert"
    disclaimer = if locale == "ko", do: "투자 조언이 아닙니다.", else: "This is not investment advice."

    body = """
    #{subject}

    #{row["reason"]}
    Source time: #{row["source_at"]}

    #{disclaimer}
    Unsubscribe: #{unsubscribe_url}
    """

    email =
      new()
      |> to(row["email"])
      |> from({Settings.get(:smtp_from_name, "Stonks Radar"), Settings.get(:smtp_from_email)})
      |> subject(subject)
      |> text_body(body)

    case Mailer.deliver(email) do
      {:ok, _metadata} ->
        update_delivery(row["id"], "email_accepted")
        {:ok, %{status: "accepted"}}

      {:error, reason} ->
        update_delivery(row["id"], "email_failed")
        {:error, reason}
    end
  end

  defp update_delivery(event_id, status) do
    Sql.execute("update ticker_alert_event set delivery_status = $2 where id = $1", [
      event_id,
      status
    ])
  rescue
    _ -> :ok
  end
end
