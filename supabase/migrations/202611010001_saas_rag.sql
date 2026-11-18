-- TubeSage SaaS schema: Clerk is the identity provider; Supabase is the
-- authoritative store for plans, conversations, chat history, and embeddings.
create extension if not exists vector with schema extensions;
create extension if not exists pgcrypto with schema extensions;

create table if not exists public.users (
  id text primary key, -- Clerk user ID
  email text,
  display_name text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create table if not exists public.subscriptions (
  user_id text primary key references public.users(id) on delete cascade,
  tier text not null default 'starter' check (tier in ('starter', 'pro', 'enterprise')),
  status text not null default 'active' check (status in ('active', 'trialing', 'past_due', 'canceled')),
  video_minutes_limit integer,
  chat_queries_per_day integer,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint starter_video_limit check (tier <> 'starter' or video_minutes_limit = 15),
  constraint pro_video_limit check (tier <> 'pro' or video_minutes_limit is null)
);

create or replace function public.create_starter_subscription()
returns trigger language plpgsql security definer set search_path = public as $$
begin
  insert into public.subscriptions(user_id, tier, status, video_minutes_limit, chat_queries_per_day)
  values (new.id, 'starter', 'active', 15, 30)
  on conflict (user_id) do nothing;
  return new;
end;
$$;

drop trigger if exists users_create_starter_subscription on public.users;
create trigger users_create_starter_subscription
after insert on public.users
for each row execute function public.create_starter_subscription();

create table if not exists public.chat_threads (
  id text primary key default gen_random_uuid()::text,
  user_id text not null references public.users(id) on delete cascade,
  video_id text,
  title text,
  status text not null default 'active' check (status in ('pending', 'active', 'failed', 'archived')),
  ingestion_job_id text,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  last_message_at timestamptz
);
create index if not exists chat_threads_user_recent_idx
  on public.chat_threads(user_id, created_at desc);
create unique index if not exists chat_threads_ingestion_job_idx
  on public.chat_threads(ingestion_job_id) where ingestion_job_id is not null;

create table if not exists public.chat_messages (
  id bigint generated always as identity primary key,
  thread_id text not null references public.chat_threads(id) on delete cascade,
  role text not null check (role in ('user', 'assistant')),
  content text not null,
  citations jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);
create index if not exists chat_messages_thread_recent_idx
  on public.chat_messages(thread_id, created_at desc);

create table if not exists public.vector_embeddings (
  id bigint generated always as identity primary key,
  thread_id text not null references public.chat_threads(id) on delete cascade,
  video_id text not null,
  chunk_id text not null,
  ordinal integer not null,
  start_seconds double precision not null,
  end_seconds double precision not null,
  chapter_title text not null default 'Overview',
  token_count integer not null default 0,
  text_hash text not null default '',
  content text not null,
  embedding extensions.vector(1536) not null,
  created_at timestamptz not null default now(),
  unique(thread_id, chunk_id)
);
create index if not exists vector_embeddings_thread_video_idx
  on public.vector_embeddings(thread_id, video_id, ordinal);
create index if not exists vector_embeddings_hnsw_idx
  on public.vector_embeddings using hnsw (embedding extensions.vector_cosine_ops);
create index if not exists vector_embeddings_content_fts_idx
  on public.vector_embeddings using gin (to_tsvector('simple', content));

create table if not exists public.evaluation_runs (
  run_id text primary key,
  thread_id text not null references public.chat_threads(id) on delete cascade,
  video_id text not null,
  question text not null,
  trace jsonb not null,
  created_at timestamptz not null default now()
);
create index if not exists evaluation_runs_thread_recent_idx
  on public.evaluation_runs(thread_id, created_at desc);

create or replace function public.create_chat_thread(p_user_id text, p_video_id text, p_title text default null)
returns public.chat_threads
language plpgsql
security definer
set search_path = public
as $$
declare
  created public.chat_threads;
begin
  perform pg_advisory_xact_lock(hashtextextended(p_user_id, 1));

  insert into public.chat_threads(user_id, video_id, title, status)
  values (p_user_id, p_video_id, p_title, 'pending')
  returning * into created;

  delete from public.chat_threads
  where user_id = p_user_id
    and id not in (
      select id from public.chat_threads
      where user_id = p_user_id
      order by created_at desc, id desc
      limit 5
    );

  return created;
end;
$$;

create or replace function public.match_thread_embeddings(
  query_embedding extensions.vector(1536),
  match_thread_id text,
  match_video_id text,
  match_count integer default 25
)
returns table (
  chunk_id text,
  video_id text,
  ordinal integer,
  start_seconds double precision,
  end_seconds double precision,
  chapter_title text,
  token_count integer,
  text_hash text,
  content text,
  embedding extensions.vector(1536),
  similarity double precision
)
language sql
stable
security invoker
set search_path = public, extensions
as $$
  select v.chunk_id, v.video_id, v.ordinal, v.start_seconds, v.end_seconds,
         v.chapter_title, v.token_count, v.text_hash, v.content, v.embedding,
         1 - (v.embedding <=> query_embedding) as similarity
  from public.vector_embeddings v
  where v.thread_id = match_thread_id and v.video_id = match_video_id
  order by v.embedding <=> query_embedding
  limit greatest(1, least(match_count, 100));
$$;

alter table public.users enable row level security;
alter table public.subscriptions enable row level security;
alter table public.chat_threads enable row level security;
alter table public.chat_messages enable row level security;
alter table public.vector_embeddings enable row level security;
alter table public.evaluation_runs enable row level security;

grant select, insert, update, delete on public.users, public.subscriptions,
  public.chat_threads, public.chat_messages, public.vector_embeddings,
  public.evaluation_runs to service_role;
grant usage, select on all sequences in schema public to service_role;

-- No public/anon policies: all user-bound access goes through authenticated
-- Next.js server handlers. The service-role key must never reach the browser.
revoke all on function public.create_chat_thread(text, text, text) from public, anon, authenticated;
revoke all on function public.match_thread_embeddings(extensions.vector, text, text, integer) from public, anon, authenticated;
grant execute on function public.create_chat_thread(text, text, text) to service_role;
grant execute on function public.match_thread_embeddings(extensions.vector, text, text, integer) to service_role;
