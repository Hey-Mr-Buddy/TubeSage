import { NextRequest, NextResponse } from 'next/server';
import { backendOrigin } from '@/lib/backend-signature';

export async function GET(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path } = await context.params;
  const response = await fetch(`${backendOrigin()}/static/${path.map(encodeURIComponent).join('/')}${request.nextUrl.search}`, { cache: 'no-store' });
  return new NextResponse(response.body, { status: response.status, headers: { 'Content-Type': response.headers.get('content-type') || 'application/octet-stream', 'Cache-Control': 'no-store' } });
}
