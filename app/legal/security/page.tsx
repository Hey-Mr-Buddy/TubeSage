import Link from 'next/link';
import { SiteHeader } from '@/components/site-header';
export const dynamic = 'force-dynamic';
export default function SecurityPage() { return <><SiteHeader /><main className="section-wrap" style={{ paddingTop: 120, paddingBottom: 100 }}><div className="eyebrow">SECURITY</div><h1>Security practices</h1><p className="hero-lede">Keep Clerk and Supabase service credentials on the server. Database access is scoped to authenticated Next.js handlers, and chat vectors are filtered by both conversation and video.</p><Link href="/">Return home →</Link></main></>; }
