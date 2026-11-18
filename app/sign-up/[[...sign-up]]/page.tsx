import { SignUp } from '@clerk/nextjs';
import Link from 'next/link';

export default function SignUpPage() {
  return <main className="auth-page"><div className="auth-copy"><Link className="wordmark" href="/">▶ TubeSage</Link><h1>Your next insight<br />starts here.</h1><p>Create an account and make your video library searchable.</p></div><SignUp routing="path" path="/sign-up" signInUrl="/sign-in" signInFallbackRedirectUrl="/dashboard" fallbackRedirectUrl="/dashboard" /></main>;
}
