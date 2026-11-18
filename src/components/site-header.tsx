'use client';

import Link from 'next/link';
import { SignedIn, SignedOut, SignInButton, UserButton } from '@clerk/nextjs';

export function SiteHeader() {
  return (
    <header className="site-header">
      <Link className="wordmark" href="/"><span>▶</span> TubeSage</Link>
      <nav aria-label="Main navigation"><Link href="#features">Features</Link><Link href="#pricing">Pricing</Link><Link href="#use-cases">Use cases</Link><Link href="/docs">Docs</Link></nav>
      <div className="header-ctas"><SignedOut><SignInButton mode="redirect"><button className="login-button">Log in</button></SignInButton><Link className="button button-dark" href="/sign-up">Get started ↗</Link></SignedOut><SignedIn><Link className="button button-dark" href="/dashboard">Dashboard</Link><UserButton /></SignedIn></div>
      <details className="mobile-nav"><summary aria-label="Open navigation">☰</summary><nav><Link href="#features">Features</Link><Link href="#pricing">Pricing</Link><Link href="#use-cases">Use cases</Link><Link href="/docs">Docs</Link></nav></details>
    </header>
  );
}
