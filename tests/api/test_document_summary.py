from __future__ import annotations

from frw_api.services.document_summary import _extract_document_text


def test_extract_document_text_removes_script_content():
    title, text = _extract_document_text(
        b"""
        <html>
          <head><title>Filing title</title><script>secret = 1</script></head>
          <body><h1>Heading</h1><p>Important public filing text.</p></body>
        </html>
        """,
        "text/html",
    )

    assert title == "Filing title"
    assert "Important public filing text." in text
    assert "secret = 1" not in text
