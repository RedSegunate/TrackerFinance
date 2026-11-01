import json
import os
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env_path = ROOT / '.env'

for line in env_path.read_text(encoding='utf-8').splitlines():
    line = line.strip()
    if not line or line.startswith('#') or '=' not in line:
        continue
    key, value = line.split('=', 1)
    os.environ.setdefault(key.strip(), value.strip())

url = os.environ['SUPABASE_URL'].rstrip('/')
service_key = os.environ['SUPABASE_SERVICE_ROLE_KEY']
endpoint = f'{url}/rest/v1/sql'

sql = """
create extension if not exists pgcrypto;

create table if not exists profiles (
  id bigint primary key,
  username text,
  first_name text,
  last_name text,
  created_at timestamptz not null default now()
);

create table if not exists categories (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null,
  type text not null check (type in ('expense', 'income')),
  name text not null,
  created_at timestamptz not null default now(),
  unique (user_id, type, name)
);

create table if not exists transactions (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null,
  kind text not null check (kind in ('expense', 'income')),
  amount numeric(12,2) not null check (amount > 0),
  category text not null,
  note text,
  created_at timestamptz not null default now()
);

create index if not exists idx_transactions_user_date
  on transactions (user_id, created_at desc);

create table if not exists budgets (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null,
  category text not null,
  limit_amount numeric(12,2) not null check (limit_amount >= 0),
  created_at timestamptz not null default now(),
  unique (user_id, category)
);

create table if not exists learned_words (
  id uuid primary key default gen_random_uuid(),
  user_id bigint not null,
  word text not null,
  category text not null,
  created_at timestamptz not null default now(),
  unique (user_id, word)
);

create table if not exists bot_settings (
  id bigint primary key,
  user_id bigint not null,
  timezone text not null default 'Europe/Moscow',
  updated_at timestamptz not null default now()
);

alter table profiles enable row level security;
alter table categories enable row level security;
alter table transactions enable row level security;
alter table budgets enable row level security;
alter table learned_words enable row level security;
alter table bot_settings enable row level security;

create policy if not exists profiles_user_is_self on profiles
  for all using (id = auth.uid())
  with check (id = auth.uid());

create policy if not exists categories_user_is_self on categories
  for all using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy if not exists transactions_user_is_self on transactions
  for all using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy if not exists budgets_user_is_self on budgets
  for all using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy if not exists learned_words_user_is_self on learned_words
  for all using (user_id = auth.uid())
  with check (user_id = auth.uid());

create policy if not exists bot_settings_user_is_self on bot_settings
  for all using (user_id = auth.uid())
  with check (user_id = auth.uid());
"""

request = urllib.request.Request(
    endpoint,
    data=json.dumps({'query': sql}).encode('utf-8'),
    headers={
        'Content-Type': 'application/json',
        'apikey': service_key,
        'Authorization': f'Bearer {service_key}',
    },
    method='POST',
)

with urllib.request.urlopen(request, timeout=30) as response:
    body = response.read().decode('utf-8')
    print(f'HTTP {response.status}')
    print(body)
