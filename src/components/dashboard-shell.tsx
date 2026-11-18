'use client';

import { useEffect, useRef, useState } from 'react';
import Link from 'next/link';
import { UserButton } from '@clerk/nextjs';
import type { Subscription } from '@/lib/account';

export type ThreadSummary = {
  id: string;
  video_id: string | null;
  title: string | null;
  status: string;
  created_at: string;
  last_message_at: string | null;
};

function formatAge(value: string) {
  const date = new Date(value);
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export function DashboardShell({ initialThreads, subscription }: { initialThreads: ThreadSummary[]; subscription: Subscription }) {
  const [threads, setThreads] = useState(initialThreads);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [frameKey, setFrameKey] = useState(0);
  const [frameSrc, setFrameSrc] = useState('/rag?view=workspace');
  const [notice, setNotice] = useState('');
  const [workspaceReady, setWorkspaceReady] = useState(false);
  const workspaceInitRef = useRef<Promise<Response> | null>(null);

  useEffect(() => {
    let mounted = true;
    // React Strict Mode replays effects in development. Share one request so
    // a late duplicate Set-Cookie cannot clear a thread selected afterward.
    workspaceInitRef.current ??= fetch('/api/threads/new', { method: 'POST' });
    workspaceInitRef.current
      .then((response) => {
        if (!response.ok) throw new Error('Could not initialize the workspace session. Refresh and sign in again.');
        if (mounted) setWorkspaceReady(true);
      })
      .catch((error: unknown) => {
        if (mounted) setNotice(error instanceof Error ? error.message : 'Could not initialize the workspace session.');
      });
    const refresh = async (event: MessageEvent) => {
      if (event.origin !== window.location.origin || event.data?.type !== 'tubesage:thread-updated') return;
      const response = await fetch('/api/threads');
      if (response.ok) { const data = await response.json(); setThreads(data.threads ?? []); setSelectedId(event.data.threadId || null); }
    };
    window.addEventListener('message', refresh);
    return () => { mounted = false; window.removeEventListener('message', refresh); };
  }, []);

  async function startNewConversation() {
    const response = await fetch('/api/threads/new', { method: 'POST' });
    if (!response.ok) { setNotice('Could not start a new conversation. Refresh and try again.'); return; }
    setSelectedId(null);
    setFrameSrc('/rag?view=workspace');
    setFrameKey((value) => value + 1);
    setNotice('New isolated video conversation ready.');
  }

  async function activateThread(thread: ThreadSummary) {
    const response = await fetch('/api/threads/activate', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ thread_id: thread.id }),
    });
    if (!response.ok) { setNotice('That conversation could not be opened.'); return; }
    setSelectedId(thread.id);
    // Pass thread_id to workspace so it can load history and skip re-ingestion
    const params = new URLSearchParams({ view: 'workspace' });
    if (thread.video_id) params.set('video', thread.video_id);
    params.set('thread_id', thread.id);
    setFrameSrc(`/rag?${params.toString()}`);
    setFrameKey((value) => value + 1);
    setNotice('Conversation loaded.');
  }

  return (
    <main className="dashboard">
      <aside className="dashboard-sidebar">
        <div className="dashboard-brand"><Link className="wordmark" href="/"><span>▶</span> TubeSage</Link></div>
        <div className="workspace-label">YOUR WORKSPACE</div>
        <button className="new-conversation" onClick={startNewConversation} disabled={!workspaceReady}>＋ &nbsp; New conversation</button>
        <div className="workspace-label">RECENT CONVERSATIONS · {threads.length}/5</div>
        <div className="thread-list">{threads.length ? threads.map((thread) => <button className={`thread-item ${selectedId === thread.id ? 'selected' : ''}`} key={thread.id} disabled={!workspaceReady} onClick={() => activateThread(thread)}><b>{thread.title || (thread.video_id ? `Video ${thread.video_id}` : 'New conversation')}</b><small>{formatAge(thread.last_message_at || thread.created_at)} · {thread.status}</small></button>) : <div className="dashboard-empty">Your recent videos and chats<br />will appear here.</div>}</div>
        <div className="sidebar-plan"><small>CURRENT PLAN</small><b>{subscription.tier}</b><Link href="/#pricing">Compare plans →</Link></div>
        <div className="sidebar-user"><span>Signed in</span><UserButton /></div>
      </aside>
      <section className="dashboard-main">
        <header className="dashboard-topbar"><h1>{selectedId ? 'Continue learning' : 'Your video workspace'}</h1><span>{subscription.tier === 'starter' ? 'Starter · videos up to 15 minutes' : `${subscription.tier} plan`}</span></header>
        {notice && <div className="dashboard-notice" role="status">{notice}</div>}
        <div className="rag-frame-wrap">{workspaceReady ? <iframe key={frameKey} className="rag-frame" title="TubeSage YouTube RAG workspace" src={frameSrc} allow="clipboard-read; clipboard-write" /> : <div className="dashboard-notice" role="status">Preparing your secure workspace…</div>}</div>
      </section>
    </main>
  );
}
