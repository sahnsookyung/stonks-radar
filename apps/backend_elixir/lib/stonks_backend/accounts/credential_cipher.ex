defmodule StonksBackend.Accounts.CredentialCipher do
  @moduledoc "AES-256-GCM envelope encryption for member-owned provider credentials."

  alias StonksBackend.Settings

  @aad "stonks-radar:user-provider-connection:v1"
  @nonce_bytes 12
  @tag_bytes 16

  def encrypt(plaintext, opts \\ [])

  def encrypt(plaintext, opts) when is_binary(plaintext) do
    with true <- byte_size(plaintext) in 1..4096,
         {:ok, key} <- encryption_key(opts) do
      nonce = :crypto.strong_rand_bytes(@nonce_bytes)

      {ciphertext, tag} =
        :crypto.crypto_one_time_aead(:aes_256_gcm, key, nonce, plaintext, @aad, @tag_bytes, true)

      {:ok, %{ciphertext: ciphertext <> tag, nonce: nonce, key_version: 1}}
    else
      false -> {:error, :invalid_credential}
      error -> error
    end
  end

  def encrypt(_plaintext, _opts), do: {:error, :invalid_credential}

  def decrypt(ciphertext_and_tag, nonce, opts \\ [])

  def decrypt(ciphertext_and_tag, nonce, opts)
      when is_binary(ciphertext_and_tag) and is_binary(nonce) do
    with true <- byte_size(nonce) == @nonce_bytes,
         true <- byte_size(ciphertext_and_tag) > @tag_bytes,
         {:ok, key} <- encryption_key(opts) do
      ciphertext_size = byte_size(ciphertext_and_tag) - @tag_bytes

      <<ciphertext::binary-size(^ciphertext_size), tag::binary-size(@tag_bytes)>> =
        ciphertext_and_tag

      case :crypto.crypto_one_time_aead(
             :aes_256_gcm,
             key,
             nonce,
             ciphertext,
             @aad,
             tag,
             false
           ) do
        :error -> {:error, :decrypt_failed}
        plaintext -> {:ok, plaintext}
      end
    else
      false -> {:error, :decrypt_failed}
      error -> error
    end
  rescue
    _ -> {:error, :decrypt_failed}
  end

  def decrypt(_ciphertext, _nonce, _opts), do: {:error, :decrypt_failed}

  defp encryption_key(opts) do
    value = Keyword.get(opts, :key, Settings.get(:ticker_credential_encryption_key))

    cond do
      is_binary(value) and byte_size(value) == 32 -> {:ok, value}
      is_binary(value) -> decode_key(String.trim(value))
      true -> {:error, :encryption_key_unavailable}
    end
  end

  defp decode_key(value) do
    [Base.decode64(value), Base.url_decode64(value, padding: false)]
    |> Enum.find_value(fn
      {:ok, key} when byte_size(key) == 32 -> {:ok, key}
      _ -> nil
    end)
    |> case do
      nil -> {:error, :encryption_key_unavailable}
      result -> result
    end
  end
end
