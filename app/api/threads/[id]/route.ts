import { auth } from '@clerk/nextjs/server';
import { NextRequest, NextResponse } from 'next/server';
import { getOwnedThread } from '@/lib/account';
import { supabaseAdmin } from '@/lib/supabase-admin';

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ id: string }> }
) {
  const { userId } = await auth();
  if (!userId) return NextResponse.json({ detail: 'Sign in to continue.' }, { status: 401 });

  const { id } = await params;
  const thread = await getOwnedThread(userId, id);
  if (!thread) return NextResponse.json({ detail: 'Conversation not found.' }, { status: 404 });

  // Fetch message history
  const { data: messages, error: messagesError } = await supabaseAdmin()
    .from('chat_messages')
    .select('role, content, citations, created_at')
    .eq('thread_id', id)
    .order('created_at', { ascending: true });

  if (messagesError) {
    return NextResponse.json({ detail: messagesError.message }, { status: 500 });
  }

  return NextResponse.json({
    thread: {
      id: thread.id,
      video_id: thread.video_id,
      title: thread.title,
      status: thread.status,
    },
    messages: messages || [],
  });
}
