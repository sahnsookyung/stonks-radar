defmodule StonksBackend.Accounts.Crypto do
  @moduledoc "Compatibility crypto for legacy sessions, PBKDF2 passwords, and TOTP."

  import Bitwise

  alias StonksBackend.Settings

  @pbkdf2_iterations 260_000
  @max_pbkdf2_iterations 1_000_000
  @max_pbkdf2_salt_bytes 128
  @max_totp_window 2
  @max_totp_secret_bytes 160

  def pbkdf2_iterations, do: @pbkdf2_iterations

  def hash_secret(value) do
    :crypto.mac(
      :hmac,
      :sha256,
      Settings.get(:session_secret, "dev-session-secret-change-me"),
      value
    )
    |> Base.encode16(case: :lower)
  end

  def hash_password(password), do: hash_new_password(password)

  def hash_new_password(password), do: Argon2.hash_pwd_salt(password)

  def hash_legacy_password(password, salt \\ nil) do
    salt = salt || :crypto.strong_rand_bytes(16) |> Base.encode16(case: :lower)

    digest =
      :crypto.pbkdf2_hmac(
        :sha256,
        password <> Settings.get(:password_pepper, "dev-password-pepper-change-me"),
        salt,
        @pbkdf2_iterations,
        32
      )
      |> Base.encode16(case: :lower)

    "pbkdf2_sha256$#{@pbkdf2_iterations}$#{salt}$#{digest}"
  end

  def verify_password(_password, nil), do: false

  def verify_password(password, "pbkdf2_sha256$" <> _ = encoded) do
    with ["pbkdf2_sha256", iterations, salt, expected] <- String.split(encoded, "$", parts: 4),
         {iterations, ""} <- Integer.parse(iterations),
         true <- iterations > 0 and iterations <= @max_pbkdf2_iterations,
         true <- valid_pbkdf2_salt?(salt),
         {:ok, expected_bytes} <- decode_hex(expected),
         true <- byte_size(expected_bytes) > 0 do
      digest =
        :crypto.pbkdf2_hmac(
          :sha256,
          password <> Settings.get(:password_pepper, "dev-password-pepper-change-me"),
          salt,
          iterations,
          byte_size(expected_bytes)
        )
        |> Base.encode16(case: :lower)

      secure_compare(digest, String.downcase(expected))
    else
      _ -> false
    end
  rescue
    _ -> false
  end

  def verify_password(password, "$argon2" <> _ = encoded) do
    Argon2.verify_pass(password, encoded)
  rescue
    _ -> false
  catch
    _, _ -> false
  end

  def verify_password(_password, _encoded), do: false

  def new_token, do: 32 |> :crypto.strong_rand_bytes() |> Base.url_encode64(padding: false)

  def verify_totp(secret, code, window \\ 1) do
    verify_totp_at(secret, code, System.system_time(:second), window)
  end

  def verify_totp_at(secret, code, unix_seconds, window \\ 1) do
    normalized = String.replace(to_string(code || ""), " ", "")

    if valid_totp_input?(secret, normalized, unix_seconds, window) do
      counter = div(unix_seconds, 30)

      -window..window
      |> Enum.any?(fn offset ->
        secure_code_compare(totp_at(secret, counter + offset), normalized)
      end)
    else
      false
    end
  rescue
    _ -> false
  end

  def totp_code(secret, unix_seconds \\ System.system_time(:second)),
    do: totp_at(secret, div(unix_seconds, 30))

  def random_totp_secret do
    20
    |> :crypto.strong_rand_bytes()
    |> Base.encode32(padding: false)
  end

  defp decode_hex(value) when is_binary(value) do
    value
    |> String.downcase()
    |> Base.decode16(case: :lower)
  end

  defp decode_hex(_), do: :error

  defp valid_pbkdf2_salt?(salt) when is_binary(salt),
    do: byte_size(salt) in 1..@max_pbkdf2_salt_bytes

  defp valid_pbkdf2_salt?(_), do: false

  defp valid_totp_input?(secret, code, unix_seconds, window) do
    is_binary(secret) and byte_size(secret) in 1..@max_totp_secret_bytes and
      is_integer(unix_seconds) and unix_seconds >= 0 and
      is_integer(window) and window in 0..@max_totp_window and
      String.match?(code, ~r/^\d{6}$/)
  end

  defp secure_compare(left, right) when byte_size(left) == byte_size(right),
    do: Plug.Crypto.secure_compare(left, right)

  defp secure_compare(_, _), do: false

  defp totp_at(secret, counter) do
    key = Base.decode32!(String.upcase(String.replace(secret, " ", "")), padding: false)
    msg = <<counter::unsigned-big-integer-size(64)>>
    digest = :crypto.mac(:hmac, :sha, key, msg)
    offset = :binary.at(digest, byte_size(digest) - 1) &&& 0x0F
    <<_::binary-size(^offset), slice::binary-size(4), _::binary>> = digest
    <<int::unsigned-big-integer-size(32)>> = slice

    Integer.mod(int &&& 0x7FFF_FFFF, 1_000_000)
    |> Integer.to_string()
    |> String.pad_leading(6, "0")
  end

  defp secure_code_compare(left, right) when byte_size(left) == byte_size(right),
    do: Plug.Crypto.secure_compare(left, right)

  defp secure_code_compare(_, _), do: false
end
