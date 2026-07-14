defmodule StonksBackend.Accounts.CredentialCipherTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Accounts.CredentialCipher

  @key :crypto.strong_rand_bytes(32)

  test "round trips credentials with random AES-GCM nonces" do
    assert {:ok, first} = CredentialCipher.encrypt("private-token", key: @key)
    assert {:ok, second} = CredentialCipher.encrypt("private-token", key: @key)
    refute first.ciphertext == second.ciphertext
    refute first.nonce == second.nonce

    assert {:ok, "private-token"} =
             CredentialCipher.decrypt(first.ciphertext, first.nonce, key: @key)
  end

  test "rejects tampering, invalid keys, and oversized credentials" do
    assert {:ok, encrypted} = CredentialCipher.encrypt("private-token", key: @key)
    <<first, rest::binary>> = encrypted.ciphertext

    assert {:error, :decrypt_failed} =
             CredentialCipher.decrypt(<<Bitwise.bxor(first, 1)>> <> rest, encrypted.nonce,
               key: @key
             )

    assert {:error, :encryption_key_unavailable} =
             CredentialCipher.encrypt("private-token", key: "short")

    assert {:error, :invalid_credential} =
             CredentialCipher.encrypt(String.duplicate("x", 4097), key: @key)
  end
end
