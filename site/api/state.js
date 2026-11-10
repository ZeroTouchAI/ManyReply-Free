// What the owner edits on the dashboard: the search topics (in priority order) and repos to post next.
// It lives in data/dashboard.json in the GitHub repo, so the daily run picks it up with a plain `git pull`.
// Needs GITHUB_TOKEN in the Vercel project's environment variables: a fine-grained token for this one repo
// with "Contents: read and write". The password check happens in middleware.js before this runs.
const REPO = process.env.GITHUB_REPO || `${process.env.VERCEL_GIT_REPO_OWNER}/${process.env.VERCEL_GIT_REPO_SLUG}`;
const URL = `https://api.github.com/repos/${REPO}/contents/data/dashboard.json`;

function github(method, body) {
  return fetch(URL, {
    method,
    headers: {
      Authorization: `Bearer ${process.env.GITHUB_TOKEN}`,
      Accept: 'application/vnd.github+json',
      'User-Agent': 'manyreply-dashboard',
    },
    body: body && JSON.stringify(body),
  });
}

// Refuse anything that is not the shape the pipeline expects, so a bad save cannot break the daily run.
function clean(input) {
  const text = (v, max) => (typeof v === 'string' ? v.trim().slice(0, max) : '');
  const topics = (Array.isArray(input.topics) ? input.topics : []).slice(0, 30)
    .map((t) => ({
      name: text(t && t.name, 60),
      queries: (Array.isArray(t && t.queries) ? t.queries : []).map((q) => text(q, 80)).filter(Boolean).slice(0, 8),
    }))
    .filter((t) => t.name && t.queries.length);
  // a request is a GitHub repo, or a website to post about (the dashboard's "Post this website")
  const link = (u) => (/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.exec(text(u, 200)) || /^https:\/\/[\w-]+(\.[\w-]+)+(\/\S*)?$/.exec(text(u, 300)) || [''])[0];
  const requests = (Array.isArray(input.requests) ? input.requests : []).slice(0, 30).map(link).filter(Boolean);
  const removed = (Array.isArray(input.removed) ? input.removed : []).slice(0, 30).map(link).filter(Boolean);
  // the owner's own apps: a GitHub link, a website, or both (the DM sends the website), and an optional one-line pitch
  const seen = new Set();
  const apps = (Array.isArray(input.apps) ? input.apps : []).slice(0, 50)
    .map((a) => ({
      url: (/^https:\/\/github\.com\/[\w.-]+\/[\w.-]+$/.exec(text(a && a.url, 200)) || [''])[0],
      site: (/^https:\/\/\S+$/.exec(text(a && a.site, 300)) || [''])[0],
      pitch: text(a && a.pitch, 120),
    }))
    .filter((a) => (a.url || a.site) && !seen.has((a.url || a.site).toLowerCase()) && seen.add((a.url || a.site).toLowerCase()));
  // repos or websites the owner starred: posted more often than whatever the search finds (see CLAUDE.md)
  const favorites = [...new Set((Array.isArray(input.favorites) ? input.favorites : []).slice(0, 100).map(link).filter(Boolean))];
  return topics.length ? { topics, requests: [...new Set(requests)], removed: [...new Set(removed)], apps, favorites } : null;
}

module.exports = async (req, res) => {
  res.setHeader('Cache-Control', 'no-store');
  if (!process.env.GITHUB_TOKEN) return res.status(503).json({ error: 'GITHUB_TOKEN is not set in Vercel.' });
  const current = await github('GET');
  if (!current.ok) return res.status(502).json({ error: `GitHub said ${current.status} when reading the settings.` });
  const file = await current.json();
  if (req.method === 'GET') return res.json(JSON.parse(Buffer.from(file.content, 'base64').toString('utf8')));
  if (req.method !== 'POST') return res.status(405).json({ error: 'Use GET or POST.' });

  const next = clean(req.body || {});
  if (!next) return res.status(400).json({ error: 'A save needs at least one topic with a name and a search term.' });
  next.saved = new Date().toISOString();
  const write = await github('PUT', {
    message: 'Dashboard: owner edited topics or requests',
    content: Buffer.from(JSON.stringify(next, null, 2) + '\n').toString('base64'),
    sha: file.sha,
  });
  if (!write.ok) return res.status(502).json({ error: `GitHub said ${write.status} when saving. Reload and try again.` });
  return res.json(next);
};
