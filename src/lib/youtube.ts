export function parseYoutubeId(url: string): string | null {
  const direct = /^[A-Za-z0-9_-]{11}$/.exec(url.trim());
  if (direct) return direct[0];
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase().replace(/^www\./, '');
    let id = '';
    if (['youtube.com', 'm.youtube.com', 'music.youtube.com'].includes(host)) {
      if (parsed.pathname === '/watch') id = parsed.searchParams.get('v') ?? '';
      else if (/^\/(embed|shorts|live)\//.test(parsed.pathname)) id = parsed.pathname.split('/')[2] ?? '';
    } else if (host === 'youtu.be') id = parsed.pathname.split('/').filter(Boolean)[0] ?? '';
    return /^[A-Za-z0-9_-]{11}$/.test(id) ? id : null;
  } catch {
    return null;
  }
}
