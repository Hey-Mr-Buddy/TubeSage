import { auth } from '@clerk/nextjs/server';
import { NextRequest, NextResponse } from 'next/server';
import { getOwnedThread } from '@/lib/account';

export async function POST(request: NextRequest) {
  const { userId } = await auth();
  if (!userId) return NextResponse.json({ detail: 'Sign in to continue.' }, { status: 401 });
  const body = await request.json().catch(() => null);
  const threadId = typeof body?.thread_id === 'string' ? body.thread_id : '';
  if (!threadId) return NextResponse.json({ detail: 'A conversation is required.' }, { status: 400 });
  const thread = await getOwnedThread(userId, threadId);
  if (!thread) return NextResponse.json({ detail: 'Conversation not found.' }, { status: 404 });
  const response = NextResponse.json({ ok: true, thread_id: thread.id, video_id: thread.video_id });
  const cookieOptions = { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax' as const, path: '/', maxAge: 60 * 60 * 24 * 30 };
  response.cookies.set('ts_thread_id', thread.id, cookieOptions);
  response.cookies.set('ts_thread_continue', '1', cookieOptions);
  return response;
}
