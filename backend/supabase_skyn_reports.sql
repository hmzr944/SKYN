-- SKYN cloud backup table for skin analysis reports.
--
-- IMPORTANT: the app talks to Supabase using only the public "anon" key
-- (frontend/src/services/supabase.ts) and has NO Supabase Auth session — it
-- authenticates against the SKYN backend (Mongo-backed sessions), not Supabase.
-- That means RLS cannot scope rows by `auth.uid()`.
--
-- To keep this safe with a public anon key, this table is configured as a
-- write-only backup: the anon role may INSERT but never SELECT / UPDATE /
-- DELETE. Reading reports back always goes through the SKYN backend
-- (/api/reports), which enforces per-user access on MongoDB.
--
-- Run this whole script once in the Supabase SQL Editor.

create table if not exists public.skyn_reports (
  id text primary key,
  user_id text not null,
  global_score integer not null,
  texture integer not null,
  radiance integer not null,
  imperfections integer not null,
  hydration integer,
  elasticity integer,
  recommendations jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create index if not exists skyn_reports_user_id_idx on public.skyn_reports (user_id);

alter table public.skyn_reports enable row level security;

-- Drop old policies if this script is re-run.
drop policy if exists "anon can insert reports" on public.skyn_reports;
drop policy if exists "anon can select reports" on public.skyn_reports;
drop policy if exists "anon can update reports" on public.skyn_reports;
drop policy if exists "anon can delete reports" on public.skyn_reports;

-- Anon (the only role the app uses) may only append rows.
create policy "anon can insert reports"
  on public.skyn_reports
  for insert
  to anon
  with check (true);

-- No select/update/delete policies for anon/authenticated -> RLS denies them
-- by default, so the backup is effectively write-only from the app's side.
