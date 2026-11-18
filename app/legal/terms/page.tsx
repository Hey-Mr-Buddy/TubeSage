import Link from 'next/link';
import { SiteHeader } from '@/components/site-header';
export const dynamic = 'force-dynamic';
export default function TermsPage() { return <><SiteHeader /><main className="section-wrap" style={{ paddingTop: 120, paddingBottom: 100 }}><div className="eyebrow">LEGAL</div><h1>Terms of service</h1><p className="hero-lede">Terms for the commercial service must be reviewed and published by the service operator before public launch.</p><Link href="/">Return home →</Link></main></>; }
