import os

from scripts import verify_free_tiers


def _reset_provider_env(monkeypatch):
    verify_free_tiers._LOADED_PROVIDER_ENV_FILES = None
    for key in (
        "FRED_API_KEY",
        "KRX_OPEN_API_AUTH_KEY",
        "KRX_AUTH_KEY",
        "KRX_API_KEY",
        "DATA_GO_KR_SERVICE_KEY",
        "DATA_GO_KR_API_KEY",
        "PUBLIC_DATA_API_KEY",
        "KOREA_PUBLIC_DATA_API_KEY",
        "FINRA_API_TOKEN",
        "FINRA_API_CLIENT_ID",
        "FINRA_API_CLIENT_SECRET",
        "STONKS_SNAPSHOT_ENV_FILE",
        "STONKS_PROVIDER_ENV_FILE",
    ):
        monkeypatch.delenv(key, raising=False)


def test_build_report_loads_default_production_env_file(tmp_path, monkeypatch):
    _reset_provider_env(monkeypatch)
    secrets_dir = tmp_path / ".secrets"
    secrets_dir.mkdir()
    (secrets_dir / "stonks-radar.production.env").write_text(
        "\n".join(
            [
                "FRED_API_KEY=fred-test",
                "DATA_GO_KR_SERVICE_KEY=public-data-test",
                "FINRA_API_CLIENT_ID=finra-client",
                "FINRA_API_CLIENT_SECRET=finra-secret",
            ]
        )
    )
    monkeypatch.setattr(
        verify_free_tiers,
        "DEFAULT_PROVIDER_ENV_FILES",
        (tmp_path / ".env", secrets_dir / "stonks-radar.production.env"),
    )

    report = verify_free_tiers._build_report(include_oci=False)

    assert report["providers"]["FRED_API_KEY"] == "configured"
    assert report["providers"]["DATA_GO_KR_SERVICE_KEY"] == "configured"
    assert report["providers"]["FINRA_API_CLIENT_ID"] == "configured"
    assert report["providers"]["FINRA_API_CLIENT_SECRET"] == "configured"
    assert report["coverage"]["delayed_market_pulse"]["status"] == "configured"
    assert report["coverage"]["krx_korea_pulse"]["status"] == "configured"
    assert report["coverage"]["finra_shorts"]["status"] == "configured"
    assert report["provider_env_files_loaded"] == [str(secrets_dir / "stonks-radar.production.env")]


def test_provider_env_file_does_not_override_process_env(tmp_path, monkeypatch):
    _reset_provider_env(monkeypatch)
    env_file = tmp_path / "provider.env"
    env_file.write_text("FRED_API_KEY=file-value\n")
    monkeypatch.setenv("FRED_API_KEY", "process-value")
    monkeypatch.setenv("STONKS_PROVIDER_ENV_FILE", str(env_file))
    monkeypatch.setattr(verify_free_tiers, "DEFAULT_PROVIDER_ENV_FILES", ())

    report = verify_free_tiers._build_report(include_oci=False)

    assert report["providers"]["FRED_API_KEY"] == "configured"
    assert os.environ["FRED_API_KEY"] == "process-value"
    assert report["provider_env_files_loaded"] == [str(env_file)]
