-- ═══════════════════════════════════════════════════════════════════
--  Fin-Guard ZeroBaran — مخطط قاعدة البيانات (Supabase / PostgreSQL)
--  شغّل هذا الملف في SQL Editor داخل مشروع Supabase المجاني.
--  ملاحظة أمنية: المخطط يستهدف صندوق الخدمة (service role) من الخادم
--  فقط — لا تضع المفتاح أبداً في المتصفح أو في المستودع.
-- ═══════════════════════════════════════════════════════════════════

create table if not exists transactions (
  id           text primary key,
  date         date not null,
  kind         text not null check (kind in ('income', 'expense')),
  category     text not null,
  vendor       text default '',
  description  text default '',
  amount       numeric(18, 4) not null,
  currency     text not null default 'USD',
  tax          numeric(18, 4) default 0,
  source_file  text default '',
  source       text default '',
  confidence   numeric(3, 2) default 1.0,
  project      text default '',
  tags         text[] default '{}',
  created_at   timestamptz not null default now()
);

create index if not exists idx_transactions_date on transactions (date desc);
create index if not exists idx_transactions_kind on transactions (kind);
create index if not exists idx_transactions_category on transactions (category);
create index if not exists idx_transactions_fingerprint on transactions
  ((lower(coalesce(vendor, ''))), date, amount);

create table if not exists anomalies (
  id           bigserial primary key,
  run_date     date not null default current_date,
  severity     text not null check (severity in ('critical', 'high', 'medium', 'low', 'info')),
  title        text not null,
  detail       text default '',
  remediation  text default '',
  refs         text[] default '{}',
  amount       numeric(18, 4) default 0
);

create index if not exists idx_anomalies_run on anomalies (run_date desc);

create table if not exists scan_runs (
  id            bigserial primary key,
  run_date      date not null default current_date,
  source        text not null,
  transactions  int not null default 0,
  income        numeric(18, 4) default 0,
  expense       numeric(18, 4) default 0,
  anomalies     int default 0,
  details       jsonb default '{}'::jsonb
);

create index if not exists idx_scan_runs_date on scan_runs (run_date desc);

-- ── عرض جاهز: ملخص شهري يُستعمل في لوحات التقارير ──────────────────
create or replace view monthly_summary as
select
  date_trunc('month', date)::date as month,
  kind,
  category,
  count(*)                        as entries,
  sum(amount)                     as total,
  sum(tax)                        as tax
from transactions
group by 1, 2, 3
order by 1 desc, 2, 3;

-- ── تفعيل RLS حتى لا يصل أي مستخدم مجهول إلى البيانات ──────────────
alter table transactions enable row level security;
alter table anomalies     enable row level security;
alter table scan_runs     enable row level security;

-- لا سياسات عامة مفتوحة: الصلاحية عبر service role من الخادم فقط.
do $$
begin
  if not exists (
    select 1 from pg_policies
    where schemaname = 'public' and tablename = 'transactions'
  ) then
    create policy service_only on transactions
      for all using (false) with check (false);
  end if;
end $$;
