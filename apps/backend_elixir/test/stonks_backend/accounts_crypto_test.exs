defmodule StonksBackend.AccountsCryptoTest do
  use ExUnit.Case, async: true

  alias StonksBackend.Accounts.Crypto

  test "PBKDF2 verification accepts current FastAPI-style hashes" do
    encoded =
      "pbkdf2_sha256$260000$0123456789abcdef0123456789abcdef$" <>
        "8966fb3174de4fb29d889f130d91cdd426a2209b6ef91ef6f45fc0651e7adeb4"

    assert Crypto.verify_password("correct horse battery staple", encoded)
    refute Crypto.verify_password("wrong password", encoded)
    refute Crypto.verify_password("correct horse battery staple", "not-a-valid-hash")

    refute Crypto.verify_password(
             "correct horse battery staple",
             "pbkdf2_sha256$260000$salt$not-hex"
           )

    refute Crypto.verify_password(
             "correct horse battery staple",
             "pbkdf2_sha256$1000001$salt$00"
           )

    refute Crypto.verify_password(
             "correct horse battery staple",
             "pbkdf2_sha256$260000$#{String.duplicate("s", 129)}$00"
           )
  end

  test "new password hashes use Argon2 and remain verifiable" do
    encoded = Crypto.hash_password("correct horse battery staple")

    assert String.starts_with?(encoded, "$argon2")
    assert Crypto.verify_password("correct horse battery staple", encoded)
    refute Crypto.verify_password("wrong password", encoded)
    refute Crypto.verify_password("correct horse battery staple", "$argon2not-a-real-hash")
  end

  test "legacy PBKDF2 helper still emits FastAPI-compatible hashes" do
    encoded =
      Crypto.hash_legacy_password(
        "correct horse battery staple",
        "0123456789abcdef0123456789abcdef"
      )

    assert encoded ==
             "pbkdf2_sha256$260000$0123456789abcdef0123456789abcdef$" <>
               "8966fb3174de4fb29d889f130d91cdd426a2209b6ef91ef6f45fc0651e7adeb4"
  end

  test "secret hashes are stable HMAC digests" do
    assert Crypto.hash_secret("token") == Crypto.hash_secret("token")
    refute Crypto.hash_secret("token") == Crypto.hash_secret("other")
  end

  test "TOTP verification accepts the configured time window" do
    secret = "JBSWY3DPEHPK3PXP"
    code = Crypto.totp_code(secret, 60)

    assert code == "602287"
    assert Crypto.verify_totp_at(secret, "602 287", 60, 0)
    refute Crypto.verify_totp_at(secret, "602287", 90, 0)
    assert Crypto.verify_totp_at(secret, "602287", 90, 1)
    refute Crypto.verify_totp_at(secret, "602287", 90, 3)
    refute Crypto.verify_totp_at(secret, "602287", 90, "1")
    refute Crypto.verify_totp_at(secret, "not-6", 60, 1)
    refute Crypto.verify_totp_at(nil, "602287", 60, 1)
  end

  test "random totp secrets are base32 compatible" do
    secret = Crypto.random_totp_secret()
    assert byte_size(secret) == 32
    assert {:ok, _} = Base.decode32(secret, padding: false)
  end
end
