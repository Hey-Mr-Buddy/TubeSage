const $ = (selector) => document.querySelector(selector);
const intro = $('#intro'), workspace = $('#workspace'), form = $('#video-form');
const input = $('#video-url'), formHint = $('#form-hint'), loadButton = $('#load-button'), messages = $('#messages');
const marketingView = $('#marketing-view'), appView = $('#app-view');
let sessionId = null, toastTimer, activeStore = null, currentThreadId = null;

function showAppView() {
  marketingView.classList.add('hidden');
  appView.classList.remove('hidden');
  document.body.classList.add('app-mode');
  document.body.classList.remove('marketing-mode');
  if (sessionId) {
    intro.classList.add('hidden');
    workspace.classList.remove('hidden');
  } else {
    workspace.classList.add('hidden');
    intro.classList.remove('hidden');
    input.focus();
  }
  window.scrollTo({top: 0, behavior: 'smooth'});
}

function showMarketingView() {
  marketingView.classList.remove('hidden');
  appView.classList.add('hidden');
  document.body.classList.remove('app-mode');
  document.body.classList.add('marketing-mode');
  window.scrollTo({top: 0, behavior: 'smooth'});
}

// YouTube IFrame Player integration
window.ytPlayer = null;
window.onYouTubeIframeAPIReady = function() {
  // The player API signals readiness through this global callback.
};

function toast(message) {
  const el = $('#toast'); el.textContent = message; el.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => el.classList.remove('show'), 4200);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || 'Something went wrong. Please try again.');
  return data;
}

function formatDuration(seconds) {
  const m = Math.floor(seconds / 60), h = Math.floor(m / 60);
  return h ? `${h}h ${m % 60}m` : `${m} min`;
}

function seekToTimestamp(seconds) {
  if (window.ytPlayer && typeof window.ytPlayer.seekTo === 'function') {
    window.ytPlayer.seekTo(seconds, true);
    if (typeof window.ytPlayer.playVideo === 'function') {
      window.ytPlayer.playVideo();
    }
    toast(`Jumping to ${Math.floor(seconds / 60)}:${String(Math.floor(seconds % 60)).padStart(2, '0')}`);
  }
}

function initializeYouTubePlayer(videoId) {
  const frame = $('#video-frame');
  frame.innerHTML = '<div id="yt-player-element"></div>';
  
  if (window.YT && window.YT.Player) {
    window.ytPlayer = new YT.Player('yt-player-element', {
      videoId: videoId,
      playerVars: {
        playsinline: 1,
        rel: 0,
        enablejsapi: 1,
      },
      events: {
        onReady: () => {
          logger_log('YouTube Player initialized successfully.');
        }
      }
    });
  } else {
    // Fallback standard iframe if API is not yet ready
    frame.innerHTML = `<iframe id="yt-player-element" src="https://www.youtube-nocookie.com/embed/${encodeURIComponent(videoId)}?enablejsapi=1&rel=0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowfullscreen></iframe>`;
  }
}

function logger_log(msg) {
  console.log(`[TubeSage] ${msg}`);
}

async function loadThreadHistory(threadId) {
  try {
    const response = await fetch(`/api/threads/${threadId}`);
    if (!response.ok) throw new Error('Could not load conversation history.');
    const data = await response.json();
    return data;
  } catch (error) {
    toast(error.message);
    return null;
  }
}

async function openChat(video, skipWelcome = false) {
  marketingView.classList.add('hidden');
  appView.classList.remove('hidden');
  document.body.classList.add('app-mode');
  document.body.classList.remove('marketing-mode');
  $('#video-title').textContent = video.title;
  $('#video-detail').textContent = `${video.duration_seconds ? formatDuration(video.duration_seconds) : 'Video ready'} · ${video.transcript_language}${video.transcript_generated ? ' · auto-captions' : ''}`;
  if (video.store) renderStore(video.store);
  if (video.index_reset?.reset) $('#store-index-status').textContent = `Index reset · cleared prior chunks`;
  else $('#store-index-status').textContent = 'Active hybrid retrieval index ready';
  
  initializeYouTubePlayer(video.video_id);
  intro.classList.add('hidden');
  workspace.classList.remove('hidden');
  // Only show welcome message for new conversations, not when loading thread history
  if (!skipWelcome) {
    messages.innerHTML = '<div class="welcome-message"><div class="sparkle">✳</div><h3>Ready when you are.</h3><p>Ask about a moment, an idea, or the whole video.</p></div>';
  } else {
    messages.innerHTML = '<div class="loading-messages">Loading conversation history...</div>';
  }
  $('#question').focus();
  // Only refresh insights if we have store data (not during thread load)
  if (video.store) refreshSessionInsights();
}

function renderStore(store) {
  activeStore = store;
  $('#store-chunks').textContent = store.chunk_count ?? '—';
  $('#store-vector-count').textContent = `${store.embedding_count ?? 0} vectors`;
  $('#store-meta').textContent = `${store.backend} · ${store.embedding_count} dense vectors · ${store.chat_message_count ?? 0} saved messages`;
  $('#dashboard-store').textContent = `${store.backend} · ${store.retrieval_index}`;
}

async function pollJobStatus(jobId) {
  const deadline = Date.now() + 20 * 60 * 1000;
  while (Date.now() < deadline) {
    await new Promise((r) => setTimeout(r, 800));
    const resp = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
    const job = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(job.detail || 'Could not fetch ingestion job status.');
    formHint.textContent = `[${job.progress_percent}%] ${job.message}...`;
    if (job.status === 'ready') return job;
    if (job.status === 'failed') throw new Error(job.error || 'Ingestion failed.');
  }
  throw new Error('Video loading timed out. Check the server logs and try again.');
}

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const urlVal = input.value.trim();
  if (!urlVal) return;

  loadButton.disabled = true;
  loadButton.innerHTML = 'Ingesting…';
  formHint.classList.add('is-loading');
  formHint.textContent = 'Fetching captions, splitting the transcript, and building the retrieval index…';

  try {
    const data = await api('/api/videos', {url: urlVal});
    let videoData = data.video;
    const loadResetInfo = data.index_reset;

    // Handle asynchronous task queue jobs
    if (!videoData && data.job_id) {
      await pollJobStatus(data.job_id);
      const postIngest = await api('/api/videos', {url: urlVal});
      videoData = postIngest.video;
      if (videoData && loadResetInfo?.reset) videoData.index_reset = loadResetInfo;
    }

    const session = await api('/api/sessions', {url: urlVal});
    sessionId = session.session_id;
    openChat(videoData);
    if (window.parent !== window) window.parent.postMessage({type: 'tubesage:thread-updated', threadId: session.session_id}, window.location.origin);
  } catch (error) {
    toast(error.message);
    formHint.textContent = error.message;
  } finally {
    formHint.classList.remove('is-loading');
    loadButton.disabled = false;
    loadButton.innerHTML = 'Load video <span>→</span>';
  }
});

$('#change-video').addEventListener('click', () => {
  workspace.classList.add('hidden');
  intro.classList.remove('hidden');
  sessionId = null;
  input.focus();
});

document.querySelectorAll('[data-question]').forEach((button) =>
  button.addEventListener('click', () => {
    if (sessionId) {
      $('#question').value = button.dataset.question;
      $('#chat-form').requestSubmit();
    } else {
      input.focus();
      toast('Load a YouTube video to start asking questions.');
    }
  })
);

const metricLabels = {
  faithfulness: 'Faithfulness',
  answer_relevance: 'Answer relevance',
  context_precision: 'Context Precision@K',
  context_recall: 'Context Recall',
  groundedness: 'Video groundedness',
  citation_precision: 'Citation precision',
};

function scoreCard(label, score) {
  const card = document.createElement('div');
  card.className = 'score-card';
  const top = document.createElement('div');
  top.className = 'score-top';
  const name = document.createElement('span');
  name.textContent = label;
  const value = document.createElement('strong');
  value.innerHTML = score == null ? '—' : `${Number(score).toFixed(1)}<small>/5</small>`;
  top.append(name, value);
  card.appendChild(top);

  const track = document.createElement('div');
  track.className = 'score-track';
  const fill = document.createElement('i');
  const numScore = Number(score);
  const pct = score == null ? 0 : (numScore <= 1.0 ? numScore * 100 : (numScore / 5.0) * 100);
  fill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
  track.appendChild(fill);
  card.appendChild(track);
  return card;
}

async function refreshSessionInsights() {
  if (!sessionId) return;
  try {
    const response = await fetch(`/api/insights/${encodeURIComponent(sessionId)}`);
    if (!response.ok) return;
    const data = await response.json(), summary = data.summary;
    $('#run-count').textContent = `${summary.run_count} run${summary.run_count === 1 ? '' : 's'} · ${summary.judged_run_count} evaluated`;
    $('#dashboard-model').textContent = `Primary ${data.primary_provider} (${data.primary_model}) · fallback ${data.fallback_model || 'off'}`;
    const avgSec = summary.averages.total_ms ? (summary.averages.total_ms / 1000).toFixed(1) : '—';
    $('#dashboard-runtime').textContent = `Avg ${avgSec}s · ${summary.averages.input_tokens || 0} in / ${summary.averages.output_tokens || 0} out tokens`;
    renderStore(data.store);
    const root = $('#session-scores');
    root.innerHTML = '';
    Object.entries(metricLabels).forEach(([key, label]) => {
      if (summary.averages[key] !== undefined && summary.averages[key] !== null) {
        root.appendChild(scoreCard(label, summary.averages[key]));
      }
    });
  } catch {}
}

function addText(parent, tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = text;
  parent.appendChild(node);
  return node;
}

function buildTrace(trace) {
  const details = document.createElement('details');
  details.className = 'run-trace';
  const summary = document.createElement('summary');
  const pipe = trace.pipeline || {};
  const cacheHit = trace.generation?.provider?.includes('Cache');

  summary.textContent = `Pipeline Trace · ${trace.generation?.provider || 'RAG'} · Latency ${pipe.total_pipeline_ms || pipe.total_ms || '—'}ms ${cacheHit ? '⚡ (Cached)' : ''}`;
  details.appendChild(summary);

  const body = document.createElement('div');
  body.className = 'run-trace-body';

  const stages = document.createElement('div');
  stages.className = 'trace-stages';
  [
    [`Cache: ${pipe.cache_lookup_ms || 0}ms`, pipe.cache_lookup_ms ? 'ready' : 'idle'],
    [`Embedding: ${pipe.embedding_query_ms || 0}ms`, 'ready'],
    [`Hybrid Search + RRF: ${pipe.rrf_fusion_ms || pipe.retrieval_ms || 0}ms`, 'ready'],
    [`Cross-Encoder Rerank: ${pipe.cross_encoder_rerank_ms || 0}ms`, 'ready'],
    [`LLM Gen: ${pipe.llm_total_ms || pipe.generation_ms || 0}ms`, 'ready']
  ].forEach(([label, state]) => {
    addText(stages, 'span', `stage-chip ${state}`, label);
  });
  body.appendChild(stages);

  const grid = document.createElement('div');
  grid.className = 'trace-grid';

  // Retrieved passages section
  const ragSec = document.createElement('section');
  ragSec.className = 'trace-section';
  addText(ragSec, 'h4', '', 'Retrieved Context Passages');
  if (pipe.retrieved_chunks && pipe.retrieved_chunks.length) {
    pipe.retrieved_chunks.forEach((item) => {
      const row = document.createElement('div');
      row.className = 'retrieved-row';
      const head = document.createElement('div');
      head.className = 'retrieved-head';
      addText(head, 'strong', '', `Passage ${item.rank} · ${Math.floor(item.start_seconds / 60)}:${String(item.start_seconds % 60).padStart(2, '0')}`);
      addText(head, 'span', 'retrieval-score', `Score ${Number(item.score).toFixed(3)}`);
      row.appendChild(head);
      addText(row, 'p', 'retrieved-preview', item.preview);
      ragSec.appendChild(row);
    });
  } else {
    addText(ragSec, 'p', 'trace-empty', 'Passages retrieved via hybrid vector fusion.');
  }
  grid.appendChild(ragSec);

  // LLM evaluation section
  const evSec = document.createElement('section');
  evSec.className = 'trace-section';
  addText(evSec, 'h4', '', 'Turn Evaluation Metrics');
  const ev = trace.llm_evaluation;
  if (ev && ev.scores) {
    const evGrid = document.createElement('div');
    evGrid.className = 'eval-score-grid';
    Object.entries(ev.scores).forEach(([key, val]) => {
      const row = document.createElement('div');
      row.className = 'eval-score-row';
      addText(row, 'span', '', metricLabels[key] || key);
      addText(row, 'strong', '', `${Number(val).toFixed(1)}/5`);
      evGrid.appendChild(row);
      if (ev.notes && ev.notes[key]) {
        addText(evGrid, 'p', 'eval-note', ev.notes[key]);
      }
    });
    evSec.appendChild(evGrid);
  } else {
    addText(evSec, 'p', 'trace-empty', 'Evaluation diagnostics recorded.');
  }
  grid.appendChild(evSec);
  body.appendChild(grid);

  const foot = document.createElement('div');
  foot.className = 'generation-foot';
  addText(foot, 'span', '', `${trace.generation?.provider || 'LLM'} · ${trace.generation?.model || ''}`);
  addText(foot, 'span', '', `Total ${pipe.total_pipeline_ms || pipe.total_ms || 0}ms`);
  body.appendChild(foot);

  details.appendChild(body);
  return details;
}

function appendMessage(role, content, citations = [], trace = null, renderedHtml = null) {
  if (messages.querySelector('.welcome-message')) messages.innerHTML = '';
  const wrapper = document.createElement('div');
  wrapper.className = `message ${role}`;
  const bubble = document.createElement('div');
  bubble.className = 'bubble';

  if (role === 'assistant' && typeof renderedHtml === 'string') {
    bubble.innerHTML = renderedHtml;
  } else {
    bubble.textContent = content;
  }
  wrapper.appendChild(bubble);

  // Phase 4: Grounded UI Interactive Citations
  if (citations && citations.length) {
    const links = document.createElement('div');
    links.className = 'citations';
    citations.forEach((source) => {
      const link = document.createElement('button');
      link.className = 'citation';
      const label = source.timestamp_label || `${Math.floor(source.start_seconds / 60)}:${String(Math.floor(source.start_seconds % 60)).padStart(2, '0')}`;
      link.textContent = `▶ ${label}`;
      link.title = `${source.claim || 'Source passage'}: "${source.quote_snippet || ''}"`;

      // Interactive Player Synchronization
      link.addEventListener('click', (e) => {
        e.preventDefault();
        seekToTimestamp(source.start_seconds);
      });

      links.appendChild(link);
    });
    wrapper.appendChild(links);
  }

  if (role === 'assistant' && trace) {
    trace.store = activeStore;
    wrapper.appendChild(buildTrace(trace));
  }

  messages.appendChild(wrapper);
  messages.scrollTop = messages.scrollHeight;
}

$('#toggle-dashboard').addEventListener('click', () => {
  const panel = $('#insight-dashboard'), button = $('#toggle-dashboard');
  const opening = panel.classList.contains('hidden');
  panel.classList.toggle('hidden');
  button.setAttribute('aria-expanded', String(opening));
  button.innerHTML = opening ? 'Hide scores <span>⌃</span>' : 'Session scores <span>⌄</span>';
});

$('#chat-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const question = $('#question').value.trim();
  if (!question || !sessionId) return;

  appendMessage('user', question);
  $('#question').value = '';
  const send = $('#send-button');
  send.disabled = true;
  send.classList.add('loading');

  const typing = document.createElement('div');
  typing.className = 'message assistant typing';
  typing.innerHTML = '<div class="bubble">Searching video transcript & re-ranking…</div>';
  messages.appendChild(typing);
  messages.scrollTop = messages.scrollHeight;

  try {
    const result = await api('/api/chat', {session_id: sessionId, question});
    typing.remove();
    appendMessage('assistant', result.answer, result.citations, result.trace, result.answer_html);
    refreshSessionInsights();
  } catch (error) {
    typing.remove();
    appendMessage('assistant', error.message);
  } finally {
    send.disabled = false;
    send.classList.remove('loading');
    $('#question').focus();
  }
});

$('#question').addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    $('#chat-form').requestSubmit();
  }
});

const workspaceParams = new URLSearchParams(window.location.search);
if (workspaceParams.get('view') === 'workspace') {
  document.body.classList.add('app-mode');
  showAppView();
  const videoId = workspaceParams.get('video') || '';
  const threadId = workspaceParams.get('thread_id') || '';
  
  if (threadId) {
    // Load existing thread history
    currentThreadId = threadId;
    loadThreadHistory(threadId).then(async (data) => {
      if (data && data.thread && data.thread.video_id) {
        // Load the video directly without re-ingestion
        input.value = `https://www.youtube.com/watch?v=${data.thread.video_id}`;
        try {
          // Call preflight to get video metadata without triggering ingestion
          const preflight = await fetch('/api/videos/preflight', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({url: input.value})
          });
          const videoInfo = await preflight.json();
          
          if (preflight.ok && videoInfo) {
            // Create session for the existing thread
            const session = await api('/api/sessions', {url: input.value});
            sessionId = session.session_id;
            
            // Open chat with video info, skip welcome message
            openChat({
              video_id: data.thread.video_id,
              title: data.thread.title || videoInfo.title || 'Video',
              duration_seconds: videoInfo.duration_seconds,
              transcript_language: videoInfo.transcript_language,
              transcript_generated: videoInfo.transcript_generated,
              store: null, // Will be populated by backend
              index_reset: null
            }, true); // Skip welcome message
            
            // Render message history
            if (data.messages && data.messages.length > 0) {
              messages.innerHTML = '';
              data.messages.forEach((msg) => {
                appendMessage(msg.role, msg.content, msg.citations || []);
              });
            } else {
              // No messages in thread, show welcome
              messages.innerHTML = '<div class="welcome-message"><div class="sparkle">✳</div><h3>Ready when you are.</h3><p>Ask about a moment, an idea, or the whole video.</p></div>';
            }
            // Refresh insights after messages are loaded to get store data
            refreshSessionInsights();
          } else {
            throw new Error(videoInfo.detail || 'Could not load video information');
          }
        } catch (error) {
          toast(error.message);
        }
      }
    });
  } else if (/^[A-Za-z0-9_-]{11}$/.test(videoId)) {
    input.value = `https://www.youtube.com/watch?v=${videoId}`;
  }
} else {
  document.body.classList.add('marketing-mode');
}
document.querySelectorAll('[data-open-app]').forEach((control) => {
  control.addEventListener('click', (event) => {
    event.preventDefault();
    showAppView();
  });
});

document.querySelectorAll('[data-login-preview]').forEach((control) => {
  control.addEventListener('click', () => toast('Account sign-in is not enabled in this local demo yet.'));
});

$('#view-marketing').addEventListener('click', showMarketingView);
$('.marketing-header .brand').addEventListener('click', (event) => {
  event.preventDefault();
  showMarketingView();
});

const mobileMenu = $('.mobile-menu');
mobileMenu.addEventListener('click', () => {
  const nav = $('.marketing-nav');
  const isOpen = nav.classList.toggle('open');
  mobileMenu.setAttribute('aria-expanded', String(isOpen));
});
document.querySelectorAll('.marketing-nav a').forEach((link) => {
  link.addEventListener('click', () => {
    $('.marketing-nav').classList.remove('open');
    mobileMenu.setAttribute('aria-expanded', 'false');
  });
});

document.querySelectorAll('[data-billing]').forEach((control) => {
  control.addEventListener('click', () => {
    const period = control.dataset.billing;
    document.querySelectorAll('[data-billing]').forEach((item) => {
      const selected = item === control;
      item.classList.toggle('selected', selected);
      item.setAttribute('aria-pressed', String(selected));
    });
    document.querySelectorAll('.price-line strong[data-monthly]').forEach((price) => {
      price.textContent = price.dataset[period];
    });
    $('#billing-note').textContent = period === 'yearly'
      ? 'Billed yearly · save 20% on Pro'
      : 'Billed monthly · cancel anytime';
  });
});
