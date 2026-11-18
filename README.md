# TubeSage SaaS

TubeSage wraps the existing FastAPI YouTube RAG pipeline in a Next.js SaaS shell. Clerk authenticates users, Supabase stores accounts, tiers, conversations, messages, evaluations, and per-conversation pgvector embeddings, while FastAPI keeps transcript ingestion, chunking, retrieval, and answer generation.

## Local setup (Windows)

1. Create a Clerk application, copy its publishable and secret keys, and set the application sign-in URL to `/sign-in` and sign-up URL to `/sign-up`. Add `http://localhost:3000` as a development application URL. Use the same Clerk instance in Next.js and FastAPI.
2. Create a Supabase project, copy its project URL and service-role key, and run `supabase/migrations/202611010001_saas_rag.sql` in Supabase SQL Editor. Never expose the service-role key to browser code.
3. Copy `.env.example` to `.env.local` in the repository root. Fill `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `ANTHROPIC_API_KEY`. Leave `FASTAPI_ORIGIN=http://127.0.0.1:8000` for local development.
4. Install and run the Python service in the existing environment. FastAPI reads both `.env` and `.env.local`:

   ```powershell
   python -m venv YTChatbotVEnv
   .\YTChatbotVEnv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   python -m uvicorn app.main:app --reload
   ```
 
5. In a second terminal at the project root, install and start Next.js:

   ```powershell
   npm ci
   npm run dev
   ```

6. Open `http://localhost:3000`, create an account, and open the dashboard. Next.js forwards authenticated RAG requests to FastAPI using a signed server-to-server identity header. Set `FASTAPI_ORIGIN` to the private FastAPI URL when the services run on separate hosts.

## SaaS data and access model

- Clerk user IDs are the primary keys in `public.users`; Starter is assigned by the database trigger. Set a user's `subscriptions.tier` through an administrative billing workflow when upgrading plans. This repository does not include a payment processor.
- Starter video length is checked against public YouTube metadata before transcript ingestion. Enterprise limits use `subscriptions.video_minutes_limit`; Pro has no plan-level duration cap. The Python caption pipeline retains a defensive 24-hour ceiling.
- Each conversation gets a unique `thread_id`. Every pgvector read and write includes that thread ID and video ID. The user dashboard only lists the five most recent threads; creating a sixth removes the oldest thread and its related records through foreign-key cascades.
- Browser API requests pass through authenticated Next.js routes. The Next.js server signs forwarded FastAPI requests with an HMAC derived from the Clerk secret; FastAPI rejects unsigned or stale requests when cloud credentials are configured.
- Supabase service credentials are used only from server-side code. RLS is enabled and no anonymous table policies are created.

## Existing RAG pipeline

FastAPI retains the current resilient transcript fetcher (manual captions, auto captions, then optional Whisper), timestamped semantic chunking, dense and BM25 retrieval, rank fusion, reranking, citations, chat history, and evaluation traces. With Supabase configured, conversation vectors and messages are stored in Supabase. SQLite remains a local transcript cache and ingestion-status store. In local development, the original standalone FastAPI UI and SQLite vector workflow remain available at `http://127.0.0.1:8000`.

## Configuration notes

`.env.example` contains the Clerk, Supabase, and Anthropic keys required for setup. `ANTHROPIC_API_KEY` is used for both generation and embeddings. For cloud pgvector, embeddings are normalized to 1536 dimensions.

Starter plan enforcement, tier changes, Supabase migration, Clerk setup, and model API calls require valid external service configuration. Without those credentials, the Next.js SaaS routes cannot authenticate or persist user data.
