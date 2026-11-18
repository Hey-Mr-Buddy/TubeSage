import { NextResponse } from 'next/server';
import { backendOrigin } from '@/lib/backend-signature';

export async function GET() {
  const response = await fetch(`${backendOrigin()}/`, { cache: 'no-store' });
  if (!response.ok) return new NextResponse('RAG service unavailable', { status: 502 });
  let html = await response.text();
  html = html.replace('</head>', '<base href="/" /></head>');
  return new NextResponse(html, { headers: { 'Content-Type': 'text/html; charset=utf-8', 'Cache-Control': 'no-store' } });
}
