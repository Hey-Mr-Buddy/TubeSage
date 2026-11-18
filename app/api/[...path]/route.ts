import { auth } from '@clerk/nextjs/server';
import { NextRequest, NextResponse } from 'next/server';
import { getOwnedThread, provisionCurrentUser, readSubscription } from '@/lib/account';
import { backendHeaders, backendOrigin } from '@/lib/backend-signature';
import { supabaseAdmin } from '@/lib/supabase-admin';
import { parseYoutubeId } from '@/lib/youtube';

type Context = { params: Promise<{ path: string[] }> };
type JsonRecord = Record<string, unknown>;
const cookieOptions = { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax' as const, path: '/', maxAge: 60 * 60 * 24 * 30 };

function isJsonRecord(value: unknown): value is JsonRecord {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

async function proxy(request: NextRequest, context: Context) {
  const { userId } = await auth();
  if (!userId) return NextResponse.json({ detail: 'Sign in to continue.' }, { status: 401 });
  const account = await provisionCurrentUser(userId);
  const tier = account.tier;
  if (!['active', 'trialing'].includes(account.status)) return NextResponse.json({ detail: 'An active subscription is required.' }, { status: 403 });
  const { path: segments } = await context.params;
  const path = `/${segments.join('/')}`;
  let threadId = request.cookies.get('ts_thread_continue')?.value === '1' ? request.cookies.get('ts_thread_id')?.value || '' : '';
  let thread = threadId ? await getOwnedThread(userId, threadId) : null;
  if (!thread) threadId = '';
  let body: ArrayBuffer | undefined;
  let parsed: JsonRecord | null = null;
  if (!['GET', 'HEAD'].includes(request.method)) {
    body = await request.arrayBuffer();
    try {
      const decoded: unknown = JSON.parse(new TextDecoder().decode(body));
      if (isJsonRecord(decoded)) parsed = decoded;
    } catch { /* pass through */ }
  }
  const upstreamPath = `/api${path}${request.nextUrl.search}`;

  if (path === '/videos' && request.method === 'POST') {
    const videoUrl = typeof parsed?.url === 'string' ? parsed.url : '';
    const videoId = parseYoutubeId(videoUrl);
    if (!videoId) return NextResponse.json({ detail: 'Enter a valid YouTube video URL.' }, { status: 400 });
    const check = await fetch(`${backendOrigin()}/api/videos/preflight`, { method: 'POST', headers: backendHeaders({ method: 'POST', path: '/api/videos/preflight', userId, tier, threadId, contentType: 'application/json' }), body: JSON.stringify({ url: videoUrl }), cache: 'no-store' });
    const info = await check.json().catch(() => ({}));
    if (!check.ok) return NextResponse.json(info, { status: check.status });
    const subscription = await readSubscription(userId);
    const minutes = typeof info.duration_seconds === 'number' && Number.isFinite(info.duration_seconds) ? info.duration_seconds / 60 : Number.NaN;
    const limit = tier === 'starter' ? (subscription.video_minutes_limit ?? 15) : tier === 'enterprise' ? subscription.video_minutes_limit : null;
    if (limit !== null && (!Number.isFinite(minutes) || minutes > limit)) {
      return NextResponse.json({ detail: Number.isFinite(minutes) ? `This plan supports videos up to ${limit} minutes.` : 'Could not verify video duration. Try again later.' }, { status: 403 });
    }
    // Loading a different video always starts a distinct thread and vector namespace.
    if (thread?.video_id && thread.video_id !== videoId) thread = null;
    if (!thread) {
      const { data, error } = await supabaseAdmin().rpc('create_chat_thread', { p_user_id: userId, p_video_id: videoId, p_title: info.title || `YouTube video ${videoId}` });
      if (error || !data) return NextResponse.json({ detail: `Could not create conversation: ${error?.message || 'unknown error'}` }, { status: 500 });
      thread = data; threadId = data.id;
    } else {
      const { data, error } = await supabaseAdmin().from('chat_threads').update({ video_id: videoId, title: info.title || thread.title, status: 'pending', updated_at: new Date().toISOString() }).eq('id', threadId).eq('user_id', userId).select().single();
      if (error) return NextResponse.json({ detail: `Could not update conversation: ${error.message}` }, { status: 500 });
      thread = data;
    }
  }

  if (path.startsWith('/jobs/')) {
    const { data } = await supabaseAdmin().from('chat_threads').select('id').eq('user_id', userId).eq('ingestion_job_id', segments[1]).maybeSingle();
    if (!data) return NextResponse.json({ detail: 'Ingestion job not found.' }, { status: 404 });
    threadId = data.id;
  }
  if (path.startsWith('/insights/')) {
    const owned = await getOwnedThread(userId, segments[1]);
    if (!owned) return NextResponse.json({ detail: 'Conversation not found.' }, { status: 404 });
    threadId = owned.id;
  }
  if (['/chat', '/chat/stream', '/sessions'].includes(path) && typeof parsed?.session_id === 'string') {
    const owned = await getOwnedThread(userId, parsed.session_id);
    if (!owned) return NextResponse.json({ detail: 'Conversation not found.' }, { status: 404 });
    thread = owned; threadId = owned.id;
  }

  const headers = backendHeaders({ method: request.method, path: upstreamPath.split('?')[0], userId, tier, threadId, contentType: request.headers.get('content-type') });
  const upstream = await fetch(`${backendOrigin()}${upstreamPath}`, { method: request.method, headers, body, cache: 'no-store' });
  const result = (path === '/videos' || path.startsWith('/jobs/')) ? await upstream.clone().json().catch(() => ({})) : {};
  if (path.startsWith('/jobs/') && result.status) {
    await supabaseAdmin().from('chat_threads').update({ status: result.status === 'ready' ? 'active' : result.status === 'failed' ? 'failed' : 'pending', updated_at: new Date().toISOString() }).eq('ingestion_job_id', segments[1]).eq('user_id', userId);
  }
  const response = new NextResponse(upstream.body, { status: upstream.status, headers: { 'Content-Type': upstream.headers.get('content-type') || 'application/json', 'Cache-Control': 'no-store' } });
  if (path === '/videos' && request.method === 'POST' && threadId) {
    if (result.job_id) await supabaseAdmin().from('chat_threads').update({ ingestion_job_id: result.job_id, status: 'pending', updated_at: new Date().toISOString() }).eq('id', threadId).eq('user_id', userId);
    else if (result.status === 'ready') await supabaseAdmin().from('chat_threads').update({ ingestion_job_id: null, status: 'active', updated_at: new Date().toISOString() }).eq('id', threadId).eq('user_id', userId);
    response.cookies.set('ts_thread_id', threadId, cookieOptions);
    response.cookies.set('ts_thread_continue', '1', cookieOptions);
  }
  return response;
}

async function handle(request: NextRequest, context: Context) {
  try {
    return await proxy(request, context);
  } catch (error) {
    console.error('Authenticated RAG bridge failed:', error);
    return NextResponse.json(
      { detail: 'The video service is temporarily unavailable. Check the app configuration and try again.' },
      { status: 503 },
    );
  }
}

export const GET = handle;
export const POST = handle;
