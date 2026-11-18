import Link from 'next/link';
import { SiteHeader } from '@/components/site-header';

export default function DocsPage() {
  return <><SiteHeader /><main className="section-wrap" style={{ paddingTop: 120, paddingBottom: 100 }}><div className="eyebrow">TUBESAGE DOCUMENTATION</div><h1>From video link to cited answers.</h1><p className="hero-lede">Paste a public YouTube link in your workspace. TubeSage retrieves available captions, builds timestamped passages, and answers questions with links to supporting moments.</p><h2>Getting started</h2><ol><li>Open your <Link href="/dashboard">workspace</Link> and paste a YouTube URL.</li><li>Wait for transcript processing to finish.</li><li>Ask a question about the video and follow the timestamp citations to verify the answer.</li></ol><p>Transcript availability depends on the video and its caption tracks. Private or restricted videos may not be accessible.</p></main></>;
}
