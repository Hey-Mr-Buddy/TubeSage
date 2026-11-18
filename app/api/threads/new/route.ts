import { auth } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';
import { provisionCurrentUser } from '@/lib/account';

export async function POST() {
  const { userId } = await auth();
  if (!userId) return NextResponse.json({ detail: 'Sign in to continue.' }, { status: 401 });
  await provisionCurrentUser(userId);
  const response = NextResponse.json({ ok: true });
  response.cookies.set('ts_thread_id', '', { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 0 });
  response.cookies.set('ts_thread_continue', '', { httpOnly: true, secure: process.env.NODE_ENV === 'production', sameSite: 'lax', path: '/', maxAge: 0 });
  return response;
}
