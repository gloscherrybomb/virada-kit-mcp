"""Rate limits for a remote server, so no agent can hammer it.

Every tool call costs units (a preview or an export costs more than reading the spec). Each client (its IP, from the
proxy's headers) has a budget per ten minutes, and so does the whole server; and at most a few previews or exports are
worked out at once (the rest wait a little, then are told to retry). A local server (stdio) has no limits.
"""
import threading, time, collections

COST = {'get_kit_spec': 1, 'get_template': 1, 'list_assets': 1, 'validate_kit': 1, 'add_asset': 2, 'import_kit': 4,
        'render_sheets': 3, 'preview_kit': 4, 'compare_to_reference': 4, 'export_kit': 8}
WINDOW = 600                 # seconds
PER_CLIENT = 200             # units per client per window: a whole kit is about 50
PER_SERVER = 2000            # units for everyone together per window
HEAVY_AT_ONCE = 2            # previews / exports worked out at the same time
HEAVY_WAIT = 30              # seconds a heavy call waits for its turn

class Limiter:
    def __init__(self, per_client=PER_CLIENT, per_server=PER_SERVER, window=WINDOW, heavy=HEAVY_AT_ONCE):
        self.per_client, self.per_server, self.window = per_client, per_server, window
        self.calls = collections.defaultdict(collections.deque); self.all = collections.deque()
        self.lock = threading.Lock(); self.heavy = threading.BoundedSemaphore(heavy)

    def _spent(self, q, now):
        while q and now - q[0][0] > self.window: q.popleft()
        return sum(c for _, c in q)

    def take(self, client, tool, now=None):
        """None if the call may go ahead (and it is counted), else a message saying when to retry."""
        now = time.time() if now is None else now; cost = COST.get(tool, 2)
        with self.lock:
            q = self.calls[client]
            for queue, budget, who in ((q, self.per_client, 'you have'), (self.all, self.per_server, 'everyone has')):
                if self._spent(queue, now) + cost > budget:
                    wait = int(self.window - (now - queue[0][0])) + 1 if queue else self.window
                    return f'rate limit: {who} used this server a lot in the last {self.window // 60} minutes; try again in {wait} s'
            q.append((now, cost)); self.all.append((now, cost))
            if len(self.calls) > 5000:                                 # forget idle clients
                for k in [k for k, v in self.calls.items() if not v or now - v[-1][0] > self.window]: del self.calls[k]
        return None

def client_of(headers):
    """The caller's address as the proxy saw it (Cloudflare, then Caddy), or 'anonymous'."""
    if not headers: return 'anonymous'
    h = {k.lower(): v for k, v in headers.items()}
    return h.get('cf-connecting-ip') or (h.get('x-forwarded-for') or '').split(',')[0].strip() or h.get('x-real-ip') or 'anonymous'
