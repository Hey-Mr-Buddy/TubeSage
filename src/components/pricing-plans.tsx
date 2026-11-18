'use client';

import { useState } from 'react';
import Link from 'next/link';

const plans = [
  {
    tier: 'STARTER', audience: 'For curious minds', monthly: '$0', yearly: '$0',
    description: 'Explore what’s inside your videos.', cta: 'Start for free', href: '/sign-up',
    label: 'INCLUDES', features: ['Videos up to 15 minutes', 'Starter daily chat allowance', 'Standard response speed', 'Timestamped citations'],
  },
  {
    tier: 'PRO', audience: 'For power learners', monthly: '$19', yearly: '$15.20',
    description: 'For a video library you use every day.', cta: 'Try Pro', href: '/sign-up', popular: true,
    label: 'EVERYTHING IN STARTER, PLUS', features: ['Unlimited video length and chats', 'Transcript and summary exports', 'Priority model execution', 'Expanded video history'],
  },
  {
    tier: 'ENTERPRISE', audience: 'For teams at scale', monthly: 'Custom', yearly: 'Custom',
    description: 'Bring video knowledge into your workflow.', cta: 'Sales contact soon', href: null,
    label: 'BUILT AROUND YOUR TEAM', features: ['Custom API integrations', 'Team workspaces and dedicated indexes', 'Custom model selection', 'Priority SLA support'],
  },
];

export function PricingPlans() {
  const [yearly, setYearly] = useState(false);
  return (
    <section className="pricing section-wrap" id="pricing">
      <div className="pricing-title"><div><div className="eyebrow">SIMPLE PLANS. CLEAR VALUE.</div><h2>Pick your pace.</h2><p>Start free. Upgrade when your video library grows.</p></div>
        <div><div className="pricing-toggle" role="group" aria-label="Billing period"><button type="button" className={!yearly ? 'selected' : ''} aria-pressed={!yearly} onClick={() => setYearly(false)}>Monthly</button><button type="button" className={yearly ? 'selected' : ''} aria-pressed={yearly} onClick={() => setYearly(true)}>Yearly <span>Save 20%</span></button></div><p className="billing-note">{yearly ? 'Pro price shown per month, billed yearly.' : 'Billed monthly · cancel anytime'}</p></div>
      </div>
      <div className="plans-grid">{plans.map((plan) => <article className={`plan ${plan.popular ? 'plan-popular' : ''}`} key={plan.tier}>
        {plan.popular && <span className="popular-tag">MOST POPULAR</span>}
        <div className="plan-kicker">{plan.tier}<small>{plan.audience}</small></div>
        <div className="plan-price">{yearly ? plan.yearly : plan.monthly}{plan.tier !== 'ENTERPRISE' && <small>/ month</small>}</div>
        <p>{plan.description}</p>
        {plan.href ? <Link className={`button ${plan.popular ? 'button-mint-dark' : 'button-outline'}`} href={plan.href}>{plan.cta} →</Link> : <button className="button button-outline" type="button" disabled>{plan.cta} →</button>}
        <hr /><label>{plan.label}</label><ul>{plan.features.map((feature) => <li key={feature}>{feature}</li>)}</ul>
      </article>)}</div>
      <p className="pricing-note">Plan preview only. Billing, exports, and enterprise services require production configuration.</p>
    </section>
  );
}
