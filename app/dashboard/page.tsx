import { auth } from '@clerk/nextjs/server';
import { redirect } from 'next/navigation';
import { DashboardShell, type ThreadSummary } from '@/components/dashboard-shell';
import { provisionCurrentUser } from '@/lib/account';
import { supabaseAdmin } from '@/lib/supabase-admin';

export const dynamic = 'force-dynamic';

export default async function DashboardPage() {
  const { userId } = await auth();
  if (!userId) redirect('/sign-in?redirect_url=%2Fdashboard');
  const subscription = await provisionCurrentUser(userId);
  const { data, error } = await supabaseAdmin()
    .from('chat_threads')
    .select('id,video_id,title,status,created_at,last_message_at')
    .eq('user_id', userId)
    .order('created_at', { ascending: false })
    .limit(5);
  if (error) throw new Error(`Could not load recent conversations: ${error.message}`);
  return <DashboardShell initialThreads={(data ?? []) as ThreadSummary[]} subscription={subscription} />;
}
