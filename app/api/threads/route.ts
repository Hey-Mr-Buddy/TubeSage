import { auth } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';
import { provisionCurrentUser } from '@/lib/account';
import { supabaseAdmin } from '@/lib/supabase-admin';

export async function GET() {
  const { userId } = await auth();
  if (!userId) return NextResponse.json({ detail: 'Sign in to continue.' }, { status: 401 });
  await provisionCurrentUser(userId);
  const { data, error } = await supabaseAdmin().from('chat_threads')
    .select('id,video_id,title,status,created_at,last_message_at')
    .eq('user_id', userId).order('created_at', { ascending: false }).limit(5);
  if (error) return NextResponse.json({ detail: error.message }, { status: 500 });
  return NextResponse.json({ threads: data ?? [] });
}
