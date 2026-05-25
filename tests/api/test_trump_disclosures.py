from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from frw_api.services.trump_disclosures import (
    _extract_recent_sec_filings,
    _oge_transaction_from_text,
    _parse_sec_ownership_xml,
    transactions_response,
)


def test_sec_recent_filings_keep_only_disclosure_forms():
    filings = _extract_recent_sec_filings(
        "DJT",
        "0001849635",
        {
            "name": "Trump Media & Technology Group Corp.",
            "tickers": ["DJT"],
            "filings": {
                "recent": {
                    "accessionNumber": ["0001849635-26-000001", "0001849635-26-000002"],
                    "form": ["8-K", "4"],
                    "filingDate": ["2026-05-20", "2026-05-21"],
                    "reportDate": ["2026-05-20", "2026-05-20"],
                    "primaryDocument": ["tm8k.htm", "form4.xml"],
                    "acceptanceDateTime": ["20260520120000", "20260521120000"],
                }
            },
        },
        max_filings=10,
    )

    assert [filing["form_type"] for filing in filings] == ["4"]
    assert filings[0]["ticker"] == "DJT"
    assert filings[0]["source_url"].endswith("/form4.xml")


def test_parse_sec_form4_xml_purchase_transaction():
    filing = {
        "source": "SEC",
        "form_type": "4",
        "filer_name": "Trump Media & Technology Group Corp.",
        "issuer_name": "Trump Media & Technology Group Corp.",
        "ticker": "DJT",
        "cik": "0001849635",
        "accession_number": "0001849635-26-000002",
        "filed_at": "2026-05-21T12:00:00+00:00",
        "raw_metadata": {},
        "transactions": [],
        "review_issues": [],
    }
    xml = b"""
    <ownershipDocument>
      <issuer>
        <issuerCik>0001849635</issuerCik>
        <issuerName>Trump Media &amp; Technology Group Corp.</issuerName>
        <issuerTradingSymbol>DJT</issuerTradingSymbol>
      </issuer>
      <reportingOwner>
        <reportingOwnerId><rptOwnerName>Example Owner</rptOwnerName></reportingOwnerId>
      </reportingOwner>
      <nonDerivativeTable>
        <nonDerivativeTransaction>
          <securityTitle><value>Class A Common Stock</value></securityTitle>
          <transactionDate><value>2026-05-20</value></transactionDate>
          <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
          <transactionAmounts>
            <transactionShares><value>1000</value></transactionShares>
            <transactionPricePerShare><value>12.34</value></transactionPricePerShare>
            <transactionAcquiredDisposedCode><value>A</value></transactionAcquiredDisposedCode>
          </transactionAmounts>
          <postTransactionAmounts>
            <sharesOwnedFollowingTransaction><value>1500</value></sharesOwnedFollowingTransaction>
          </postTransactionAmounts>
          <ownershipNature>
            <directOrIndirectOwnership><value>D</value></directOrIndirectOwnership>
          </ownershipNature>
        </nonDerivativeTransaction>
      </nonDerivativeTable>
    </ownershipDocument>
    """

    _parse_sec_ownership_xml(filing, xml)

    assert filing["parse_status"] == "parsed"
    assert filing["transactions"][0]["transaction_type"] == "purchase"
    assert filing["transactions"][0]["owner_name"] == "Example Owner"
    assert filing["transactions"][0]["shares"] == 1000


def test_parse_oge_text_row_with_valid_ticker_and_amount_range():
    filing = {
        "source": "OGE",
        "sha256": "sha256:filing",
        "filer_name": "Trump, Donald J",
    }
    transaction = _oge_transaction_from_text(
        filing,
        "Apple Inc. (AAPL) purchase 3/14/2026 no $100,001 - $250,000",
        page_number=2,
        row_number="1",
        ticker_map={"AAPL": {"cik": "0000320193", "title": "Apple Inc."}},
    )

    assert transaction is not None
    assert transaction["ticker"] == "AAPL"
    assert transaction["issuer_name"] == "Apple Inc."
    assert transaction["amount_min"] == 100001
    assert transaction["amount_max"] == 250000


def test_parse_oge_text_row_without_valid_ticker_stays_review_confidence():
    filing = {
        "source": "OGE",
        "sha256": "sha256:filing",
        "filer_name": "Trump, Donald J",
    }
    transaction = _oge_transaction_from_text(
        filing,
        "Broadcom Inc COM purchase 2/10/2028 no $1,000,001 - $5,000,000",
        page_number=2,
        row_number="1",
        ticker_map={},
    )

    assert transaction is not None
    assert transaction["ticker"] is None
    assert str(transaction["confidence"]) == "0.72"


def test_transactions_response_hides_low_confidence_rows_by_default():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                create table source_filings (
                  id integer primary key,
                  source_url text,
                  form_type text,
                  filed_at text,
                  doc_date text
                )
                """
            )
        )
        conn.execute(
            text(
                """
                create table security_transactions (
                  id integer primary key,
                  filing_id integer,
                  source text,
                  person_name text,
                  owner_name text,
                  issuer_name text,
                  ticker text,
                  transaction_type text,
                  transaction_code text,
                  transaction_date text,
                  confidence numeric
                )
                """
            )
        )
        conn.execute(
            text(
                """
                insert into source_filings (id, source_url, form_type, filed_at, doc_date)
                values (1, 'https://oge.example/report.pdf', '278-T', null, '2026-05-01'),
                       (2, 'https://sec.example/form4.xml', '4', null, '2026-05-21')
                """
            )
        )
        conn.execute(
            text(
                """
                insert into security_transactions
                  (id, filing_id, source, person_name, owner_name, issuer_name, ticker,
                   transaction_type, transaction_code, transaction_date, confidence)
                values
                  (1, 1, 'OGE', 'Donald J. Trump', null, 'Noisy bond row', null,
                   'purchase', null, '2036-07-01', 0.90),
                  (2, 2, 'SEC', 'Example Owner', 'Example Owner', 'Trump Media', 'DJT',
                   'purchase', 'P', '2026-05-21', 0.98)
                """
            )
        )

    with Session(engine) as db:
        default_payload = transactions_response(db, limit=10)
        review_payload = transactions_response(db, min_confidence=None, limit=10)

    assert [row["issuer_name"] for row in default_payload["transactions"]] == ["Trump Media"]
    assert {row["issuer_name"] for row in review_payload["transactions"]} == {"Noisy bond row", "Trump Media"}
