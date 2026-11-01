create schema if not exists tracker_finance;
set search_path to tracker_finance;

create table if not exists users (
  user_id bigint primary key,
  token text unique not null,
  created_at text not null
);

create table if not exists transactions (
  id bigserial primary key,
  user_id bigint not null,
  kind text not null,
  amount double precision not null,
  category text not null,
  note text,
  created_at text not null
);
create index if not exists idx_tx_user_date on transactions(user_id, created_at);

create table if not exists budgets (
  user_id bigint not null,
  category text not null,
  limit_amount double precision not null,
  primary key(user_id, category)
);

create table if not exists goals (
  id bigserial primary key,
  user_id bigint not null,
  title text not null,
  target_amount double precision not null,
  icon text not null default '🎯',
  saved_amount double precision not null default 0,
  created_at text not null
);

create table if not exists user_settings (
  user_id bigint primary key,
  theme text not null default 'system',
  timezone text not null default 'Europe/Moscow',
  budget_notifications integer not null default 1,
  weekly_summary integer not null default 0
);

create table if not exists deleted_transactions (
  tx_id bigint primary key,
  user_id bigint not null,
  kind text not null,
  amount double precision not null,
  category text not null,
  note text,
  created_at text not null,
  deleted_at text not null
);

create table if not exists budget_alerts (
  user_id bigint not null,
  category text not null,
  month_key text not null,
  level text not null,
  sent_at text not null,
  primary key(user_id, category, month_key, level)
);

create table if not exists weekly_reports (
  user_id bigint not null,
  week_key text not null,
  sent_at text not null,
  primary key(user_id, week_key)
);

create table if not exists rules (
  user_id bigint not null,
  word text not null,
  category text not null,
  primary key(user_id, word)
);

revoke all on schema tracker_finance from public;
alter table users enable row level security;
alter table transactions enable row level security;
alter table budgets enable row level security;
alter table goals enable row level security;
alter table user_settings enable row level security;
alter table deleted_transactions enable row level security;
alter table budget_alerts enable row level security;
alter table weekly_reports enable row level security;
alter table rules enable row level security;
