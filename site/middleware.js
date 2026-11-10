// Password gate for the private parts of the site: the dashboard and the function that saves its edits.
// The public tools page (/) is not matched and stays open.
// Set DASHBOARD_PASSWORD in the Vercel project's environment variables. With no password set, nothing opens.
export const config = { matcher: ['/dashboard', '/dashboard/:path*', '/api/:path*'] };

export default function middleware(request) {
  const password = process.env.DASHBOARD_PASSWORD;
  const header = request.headers.get('authorization') || '';
  if (password && header.startsWith('Basic ')) {
    const given = atob(header.slice(6)).split(':').slice(1).join(':'); // any username, this password
    if (given === password) return; // let the request through
  }
  return new Response('Password required.', {
    status: 401,
    headers: { 'WWW-Authenticate': 'Basic realm="ManyReply dashboard"', 'Cache-Control': 'no-store' },
  });
}
