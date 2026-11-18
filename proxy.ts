import { clerkMiddleware } from '@clerk/nextjs/server';
import { NextResponse } from 'next/server';

const publicPaths = new Set(['/', '/sign-in', '/sign-up']);

function isPublicPath(pathname: string) {
  return publicPaths.has(pathname) || pathname.startsWith('/sign-in/') || pathname.startsWith('/sign-up/');
}

export default clerkMiddleware(async (auth, request) => {
  const { pathname } = request.nextUrl;

  // Keep the public site and Clerk's own sign-in/up pages outside access checks.
  if (isPublicPath(pathname)) return;

  // APIs must return machine-readable 401s. Redirecting fetch/XHR to the login
  // page makes the client parse HTML as JSON and often looks like a login loop.
  if (pathname.startsWith('/api/')) {
    const { userId } = await auth();
    if (!userId) return NextResponse.json({ detail: 'Sign in to continue.' }, { status: 401 });
    return;
  }

  if (pathname === '/dashboard' || pathname.startsWith('/dashboard/')) {
    await auth.protect();
  }
});

export const config = {
  matcher: [
    '/((?!_next|[^?]*\\.(?:html?|css|js(?!on)|jpe?g|webp|png|gif|svg|ttf|woff2?|ico|csv|docx?|xlsx?|zip|webmanifest)).*)',
    '/(api|trpc)(.*)',
    '/__clerk/(.*)',
  ],
};
