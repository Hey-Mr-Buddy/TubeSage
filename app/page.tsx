import Link from 'next/link';
import { SiteHeader } from '@/components/site-header';
import { PricingPlans } from '@/components/pricing-plans';

const features = [
  ['01', 'Instant transcript ingestion', 'Available captions become timestamped passages, ready to search and cite.'],
  ['02', 'Context-aware semantic search', 'Ask in your own words and find the relevant ideas across a long video.'],
  ['03', 'Timestamped citations', 'Jump straight to the source moment and verify the answer in context.'],
  ['04', 'Multilingual understanding', 'Explore videos through the caption languages available for each source.'],
];

export default function HomePage() {
  return (
    <>
      <SiteHeader />
      <main>
        <section className="hero section-wrap" id="home">
          <div className="hero-copy">
            <div className="eyebrow"><span className="pulse-dot" /> VIDEO KNOWLEDGE, ON DEMAND</div>
            <h1>Turn any video into a <em>conversation.</em></h1>
            <p className="hero-lede">Search hours of YouTube in seconds. Get grounded answers, clear citations, and a link back to the moment that matters.</p>
            <div className="hero-actions"><Link className="button button-mint" href="/dashboard">Start free <span>→</span></Link><Link className="button button-glass" href="#pricing">Explore plans</Link></div>
            <p className="hero-caption">Start with a public YouTube link · No setup required</p>
          </div>
          <div className="product-card" aria-label="TubeSage product preview">
            <div className="product-top"><span><i /><i /><i /></span><small>tubesage / workspace</small><b>● READY</b></div>
            <div className="preview-video"><div className="preview-play">▶</div><div className="preview-video-label"><b>THE SCIENCE OF FOCUS</b><small>18:42 · 12 chapters</small></div><div className="preview-progress"><i /></div></div>
            <div className="preview-chat"><p className="preview-question">What does the speaker recommend for deep work?</p><div className="preview-answer"><span>✳</span><div><p>Protect a focused block, remove distractions, then take a real break between sessions.</p><small>◷ &nbsp; 04:12 · Focused work</small></div></div><div className="preview-input">Ask anything about this video <b>↑</b></div></div>
            <div className="preview-float">↗ &nbsp; Answer linked to 04:12</div>
          </div>
        </section>
        <section className="audience-strip section-wrap"><span>BUILT FOR PEOPLE WHO LEARN FROM VIDEO</span><div>CREATORS <i /> EDUCATORS <i /> RESEARCHERS <i /> PRODUCT TEAMS</div></section>
        <section className="section-wrap features-section" id="features"><div className="section-title"><div className="eyebrow">LESS SEARCHING. MORE UNDERSTANDING.</div><h2>Your video has the answer.<br /><span>Now you can find it.</span></h2><p>Move from passive watching to source-linked knowledge in a few clicks.</p></div><div className="feature-grid">{features.map(([index, title, body]) => <article className="feature-card" key={index}><span className="feature-number">{index}</span><div className={`feature-glyph glyph-${index}`}>{['↯', '⌕', '◷', '文'][Number(index) - 1]}</div><h3>{title}</h3><p>{body}</p></article>)}</div></section>
        <section className="use-cases section-wrap" id="use-cases"><div><div className="eyebrow">ONE WORKFLOW. MANY WAYS TO LEARN.</div><h2>Make every minute<br />of video count.</h2></div><div className="use-case-list"><article><span>01</span><div><b>Learning</b><p>Review lectures and tutorials without replaying the whole thing.</p></div></article><article><span>02</span><div><b>Research</b><p>Find claims, examples, and sources buried in long interviews.</p></div></article><article><span>03</span><div><b>Teams</b><p>Make demos and recorded explainers easier to search and share.</p></div></article></div></section>
        <section className="proof section-wrap"><div><div className="eyebrow">MADE TO BE USEFUL</div><h2>Knowledge that<br />keeps its source.</h2><p>We’re opening TubeSage to early users. Product metrics and customer stories will appear here as the community grows.</p></div><div className="proof-grid"><article><b>—</b><span>active learners</span><small>Early access</small></article><article><b>—</b><span>video hours explored</span><small>Early access</small></article><article><b>—</b><span>answers with sources</span><small>Measured in product</small></article><article className="quote-placeholder"><strong>“</strong><p>Customer stories are being collected. Be among the first to shape what comes next.</p><Link href="/sign-up">Join early access ↗</Link></article></div></section>
        <PricingPlans />
        <section className="final-cta section-wrap"><div><div className="eyebrow">YOUR NEXT INSIGHT IS ALREADY IN THERE</div><h2>Stop scrubbing.<br />Start asking.</h2></div><Link className="button button-mint" href="/dashboard">Start with a video →</Link></section>
      </main>
      <footer className="site-footer section-wrap"><div className="footer-brand"><Link className="wordmark" href="/">▶ TubeSage</Link><p>Your video library, made interactive.</p></div><div><b>PRODUCT</b><Link href="#features">Features</Link><Link href="#pricing">Pricing</Link><Link href="#use-cases">Use cases</Link></div><div><b>RESOURCES</b><Link href="/docs">Documentation</Link><Link href="/dashboard">Workspace</Link></div><div><b>COMPANY</b><a href="mailto:hello@tubesage.app">Contact</a><Link href="#home">About TubeSage</Link></div><div><b>LEGAL</b><Link href="/legal/terms">Terms</Link><Link href="/legal/privacy">Privacy</Link><Link href="/legal/security">Security</Link></div><small className="copyright">© 2026 TubeSage · Captions are the source. You stay in control.</small></footer>
    </>
  );
}

