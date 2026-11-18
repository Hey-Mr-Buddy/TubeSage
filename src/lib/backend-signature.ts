import 'server-only';
import { createHmac } from 'node:crypto';
import type { Tier } from '@/lib/account';

export function backendHeaders(input: {
  method: string;
  path: string;
  userId: string;
  tier: Tier;
  threadId?: string;
  contentType?: string | null;
}) {
  const secret = process.env.CLERK_SECRET_KEY;
  if (!secret) throw new Error('Clerk server credentials are not configured.');
  const timestamp = String(Math.floor(Date.now() / 1000));
  const threadId = input.threadId ?? '';
  const canonical = [timestamp, input.method.toUpperCase(), input.path, input.userId, input.tier, threadId].join('\n');
  const signature = createHmac('sha256', secret).update(canonical).digest('hex');
  const headers: Record<string, string> = {
    'X-TubeSage-User': input.userId,
    'X-TubeSage-Tier': input.tier,
    'X-TubeSage-Thread': threadId,
    'X-TubeSage-Timestamp': timestamp,
    'X-TubeSage-Signature': signature,
  };
  if (input.contentType) headers['Content-Type'] = input.contentType;
  return headers;
}

export function backendOrigin() {
  return process.env.FASTAPI_ORIGIN || 'http://127.0.0.1:8000';
}
