import { SignIn } from '@clerk/nextjs';
import Link from 'next/link';

export default function SignInPage() {
  return <main className="auth-page"><div className="auth-copy"><Link className="wordmark" href="/">▶ TubeSage</Link><h1>Welcome back.</h1><p>Pick up where your questions left off.</p></div><SignIn routing="path" path="/sign-in" signUpUrl="/sign-up" fallbackRedirectUrl="/dashboard" signUpFallbackRedirectUrl="/dashboard" /></main>;
}
