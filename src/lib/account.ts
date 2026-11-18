import 'server-only';
import { currentUser } from '@clerk/nextjs/server';
import { supabaseAdmin } from '@/lib/supabase-admin';

export type Tier = 'starter' | 'pro' | 'enterprise';
export type Subscription = {
  tier: Tier;
  status: string;
  video_minutes_limit: number | null;
  chat_queries_per_day: number | null;
};

export async function provisionCurrentUser(userId: string) {
  const profile = await currentUser();
  const email = profile?.primaryEmailAddress?.emailAddress ?? null;
  const displayName = profile?.fullName ?? profile?.username ?? null;
  const supabase = supabaseAdmin();
  const { error } = await supabase.from('users').upsert({
    id: userId,
    email,
    display_name: displayName,
    updated_at: new Date().toISOString(),
  }, { onConflict: 'id' });
  if (error) throw new Error(`Could not sync Clerk user to Supabase: ${error.message}`);

  const { data: subscription, error: subError } = await supabase
    .from('subscriptions')
    .select('tier,status,video_minutes_limit,chat_queries_per_day')
    .eq('user_id', userId)
    .maybeSingle();
  if (subError) throw new Error(`Could not read subscription tier: ${subError.message}`);
  if (subscription) return subscription as Subscription;

  // The SQL trigger normally creates Starter. This upsert also heals accounts
  // created before the migration trigger was installed.
  const { data: starter, error: createError } = await supabase
    .from('subscriptions')
    .upsert({ user_id: userId, tier: 'starter', status: 'active', video_minutes_limit: 15, chat_queries_per_day: 30 }, { onConflict: 'user_id' })
    .select('tier,status,video_minutes_limit,chat_queries_per_day')
    .single();
  if (createError) throw new Error(`Could not initialize Starter subscription: ${createError.message}`);
  return starter as Subscription;
}

export async function readSubscription(userId: string) {
  const { data, error } = await supabaseAdmin()
    .from('subscriptions')
    .select('tier,status,video_minutes_limit,chat_queries_per_day')
    .eq('user_id', userId)
    .maybeSingle();
  if (error) throw new Error(`Could not read subscription tier: ${error.message}`);
  if (!data) throw new Error('Subscription was not initialized. Reload the dashboard.');
  return data as Subscription;
}

export async function getOwnedThread(userId: string, threadId: string) {
  const { data, error } = await supabaseAdmin()
    .from('chat_threads')
    .select('id,user_id,video_id,title,status,ingestion_job_id,created_at,updated_at,last_message_at')
    .eq('id', threadId)
    .eq('user_id', userId)
    .maybeSingle();
  if (error) throw new Error(`Could not read conversation: ${error.message}`);
  return data;
}
