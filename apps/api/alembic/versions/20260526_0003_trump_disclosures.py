"""trump-family public disclosure tracker

Revision ID: 20260526_0003
Revises: 20260525_0002
Create Date: 2026-05-26
"""

from __future__ import annotations

from alembic import op

revision = "20260526_0003"
down_revision = "20260525_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        create table if not exists watched_people (
          id bigserial primary key,
          canonical_name text not null unique,
          category text not null check (category in (
            'donald_trump','spouse','dependent_child','adult_family','related_entity'
          )),
          aliases text[] not null default '{}',
          tickers text[] not null default '{}',
          sec_ciks text[] not null default '{}',
          oge_names text[] not null default '{}',
          notes text,
          created_at timestamptz not null default now()
        );

        create table if not exists source_filings (
          id bigserial primary key,
          source text not null check (source in ('OGE','SEC')),
          form_type text not null,
          filer_name text,
          issuer_name text,
          ticker text,
          cik text,
          accession_number text,
          doc_date date,
          filed_at timestamptz,
          source_url text not null,
          local_path text,
          sha256 text not null,
          raw_metadata jsonb not null default '{}'::jsonb,
          parse_status text not null default 'pending',
          created_at timestamptz not null default now(),
          unique (source, sha256)
        );

        create index if not exists source_filings_source_doc_date_idx
          on source_filings(source, doc_date desc nulls last, created_at desc);
        create index if not exists source_filings_ticker_idx
          on source_filings(ticker)
          where ticker is not null;
        create index if not exists source_filings_cik_idx
          on source_filings(cik)
          where cik is not null;

        create table if not exists security_transactions (
          id bigserial primary key,
          filing_id bigint not null references source_filings(id) on delete cascade,
          source text not null check (source in ('OGE','SEC')),
          person_name text,
          owner_name text,
          issuer_name text,
          ticker text,
          cik text,
          asset_description text,
          transaction_type text,
          transaction_code text,
          transaction_date date,
          amount_min numeric,
          amount_max numeric,
          shares numeric,
          price numeric,
          direct_or_indirect text,
          ownership_nature text,
          post_transaction_shares numeric,
          is_late boolean,
          source_page integer,
          confidence numeric,
          raw_row jsonb not null default '{}'::jsonb,
          dedupe_key text not null,
          created_at timestamptz not null default now(),
          unique (dedupe_key)
        );

        create index if not exists security_transactions_person_idx
          on security_transactions(person_name, transaction_date desc nulls last);
        create index if not exists security_transactions_ticker_idx
          on security_transactions(ticker, transaction_date desc nulls last)
          where ticker is not null;
        create index if not exists security_transactions_source_idx
          on security_transactions(source, transaction_date desc nulls last);

        create table if not exists parse_review_queue (
          id bigserial primary key,
          filing_id bigint references source_filings(id) on delete cascade,
          issue_type text not null,
          raw_excerpt text,
          suggested_fix jsonb,
          status text not null default 'open' check (status in ('open','resolved','dismissed')),
          created_at timestamptz not null default now()
        );

        create index if not exists parse_review_queue_status_idx
          on parse_review_queue(status, created_at desc);

        insert into watched_people(canonical_name, category, aliases, tickers, sec_ciks, oge_names, notes)
        values
          (
            'Donald J. Trump', 'donald_trump',
            array['Donald Trump','Donald J Trump','President Trump'],
            '{}', '{}',
            array['Trump, Donald J.','Trump, Donald J'],
            'OGE Form 278e/278-T coverage only; does not imply private brokerage visibility.'
          ),
          (
            'Melania Trump', 'spouse',
            array['Melania Trump','Trump, Melania'],
            '{}', '{}', '{}',
            'Only tracked where included in Donald J. Trump OGE reports or independent public filings.'
          ),
          (
            'Donald Trump Jr.', 'adult_family',
            array['Donald Trump Jr','Donald J. Trump Jr.','Trump, Donald J. Jr.'],
            '{}', '{}', '{}',
            'SEC-only unless a public filing names the person or entity.'
          ),
          (
            'Eric Trump', 'adult_family',
            array['Eric Trump','Trump, Eric'],
            '{}', '{}', '{}',
            'SEC-only unless a public filing names the person or entity.'
          ),
          (
            'Ivanka Trump', 'adult_family',
            array['Ivanka Trump','Trump, Ivanka'],
            '{}', '{}', '{}',
            'SEC-only unless a public filing names the person or entity.'
          ),
          (
            'Jared Kushner', 'adult_family',
            array['Jared Kushner','Kushner, Jared'],
            '{}', '{}', '{}',
            'SEC-only unless a public filing names the person or entity.'
          ),
          (
            'Trump Media & Technology Group', 'related_entity',
            array['Trump Media','TMTG','Trump Media & Technology Group Corp.'],
            array['DJT'], array['0001849635'], '{}',
            'Related public-company entity; filings are sourced from SEC EDGAR.'
          )
        on conflict (canonical_name) do update
        set category = excluded.category,
            aliases = excluded.aliases,
            tickers = excluded.tickers,
            sec_ciks = excluded.sec_ciks,
            oge_names = excluded.oge_names,
            notes = excluded.notes;
        """
    )


def downgrade() -> None:
    op.execute(
        """
        drop index if exists parse_review_queue_status_idx;
        drop table if exists parse_review_queue;
        drop index if exists security_transactions_source_idx;
        drop index if exists security_transactions_ticker_idx;
        drop index if exists security_transactions_person_idx;
        drop table if exists security_transactions;
        drop index if exists source_filings_cik_idx;
        drop index if exists source_filings_ticker_idx;
        drop index if exists source_filings_source_doc_date_idx;
        drop table if exists source_filings;
        drop table if exists watched_people;
        """
    )
