from __future__ import annotations

from pathlib import Path

from frw_api.core.settings import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_caddy_assets_do_not_use_spa_fallback() -> None:
    caddyfile = (ROOT / "infra" / "Caddyfile").read_text()
    assets_handle = caddyfile.split("handle /assets/*", 1)[1].split("handle /map/*", 1)[0]

    assert "file_server" in assets_handle
    assert "try_files" not in assets_handle
    assert "/index.html" not in assets_handle
    assert "max-age=31536000, immutable" in assets_handle


def test_public_seo_files_exist_and_are_not_spa_html() -> None:
    robots = (ROOT / "apps" / "web" / "public" / "robots.txt").read_text()
    sitemap = (ROOT / "apps" / "web" / "public" / "sitemap.xml").read_text()

    assert "User-agent: *" in robots
    assert "Sitemap: https://stonks.sookyungahn.com/sitemap.xml" in robots
    assert "<urlset" in sitemap
    assert "https://stonks.sookyungahn.com/en" in sitemap
    assert "<!doctype html>" not in robots.lower()
    assert "<!doctype html>" not in sitemap.lower()


def test_caddy_snapshot_and_html_cache_policies_are_explicit() -> None:
    caddyfile = (ROOT / "infra" / "Caddyfile").read_text()

    assert "handle /public/latest/manifest.json" in caddyfile
    assert 'Cache-Control "no-cache, max-age=0, must-revalidate' in caddyfile
    assert "no-transform" in caddyfile
    assert 'Cache-Control "public, max-age=60, stale-while-revalidate=300"' in caddyfile


def test_production_csp_does_not_allow_localhost() -> None:
    index_html = (ROOT / "apps" / "web" / "index.html").read_text()
    caddyfile = (ROOT / "infra" / "Caddyfile").read_text()

    assert "Content-Security-Policy" not in index_html
    assert "http://localhost:8000" not in caddyfile
    assert "connect-src 'self'" in caddyfile


def test_cloudflare_iac_keeps_injected_scripts_disabled() -> None:
    cloudflare_tf = (ROOT / "infra" / "cloudflare" / "terraform" / "main.tf").read_text()

    assert 'setting_id = "rocket_loader"' in cloudflare_tf
    assert 'value      = "off"' in cloudflare_tf
    assert 'resource "cloudflare_web_analytics_site" "stonks_radar"' in cloudflare_tf
    assert "auto_install = false" in cloudflare_tf


def test_production_cors_excludes_dev_origins() -> None:
    settings = Settings(app_env="production", public_base_url="https://stonks.sookyungahn.com")

    assert settings.cors_origin_list == ["https://stonks.sookyungahn.com"]
