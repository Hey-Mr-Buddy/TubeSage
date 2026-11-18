import Link from 'next/link';
import { SiteHeader } from '@/components/site-header';
export const dynamic = 'force-dynamic';
export default function PrivacyPage() { return <><SiteHeader /><main className="section-wrap" style={{ paddingTop: 120, paddingBottom: 100 }}><div className="eyebrow">LEGAL</div><h1>Privacy</h1><p className="hero-lede">A production privacy notice describing account, conversation, transcript, retention, and processor handling must be published before public launch.</p><Link href="/">Return home →</Link></main></>; }
