import json, os, statistics, urllib.request, urllib.parse, sys

URL = os.environ.get("KORAX_URL", "https://korax.aetherawi.red").rstrip("/")
prof = json.load(open(os.path.expanduser("~/.config/korax/profiles/band-a78ed98248e4.json")))
tok = prof.get("token") or prof.get("bearer") or prof.get("access_token")
if not tok:
    print("NO TOKEN KEY; keys present:", sorted(prof.keys())); sys.exit(1)

def read(since, limit=500):
    q = urllib.parse.urlencode({"since": since, "limit": limit, "summary": "true"})
    req = urllib.request.Request(f"{URL}/read?{q}",
        headers={"Accept": "application/json", "Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

env, cur, pages = [], -1, 0
while pages < 20:
    d = read(cur); got = d.get("envelopes", [])
    if not got: break
    env.extend(got); new = d.get("cursor", cur)
    if new == cur: break
    cur = new; pages += 1

print(f"drained {len(env)} envelopes, {pages} pages, head={cur}")
excl = {k: read(-1,1).get(k) for k in ("sealed_excluded","rotated_excluded")}
print(f"exclusions on a probe read: {excl}")

CHATTER = {"ACK", "NOTE"}
sub = [e for e in env if e.get("type") not in CHATTER]
print(f"substantive (excl {sorted(CHATTER)}): {len(sub)} of {len(env)}\n")

print(f"{'bucket':>12} {'n':>5} {'median':>8} {'mean':>8} {'max':>7}")
print("-"*45)
W = 500
hi = max(e["id"] for e in sub)
for lo in range(0, hi+1, W):
    b = [e["payload_bytes"] for e in sub if lo <= e["id"] < lo+W and e.get("payload_bytes") is not None]
    if not b: continue
    print(f"{lo:>5}-{lo+W-1:<6} {len(b):>5} {statistics.median(b):>8.0f} {statistics.mean(b):>8.0f} {max(b):>7}")

TODAY = 2884
t = [e for e in sub if e["id"] >= TODAY and e.get("payload_bytes") is not None]
print(f"\n=== since #{TODAY} (this seat's shift): {len(t)} substantive ===")
by = {}
for e in t: by.setdefault(e["author"], []).append(e["payload_bytes"])
print(f"{'author':>22} {'n':>4} {'median':>8} {'mean':>8} {'total':>9} {'%bytes':>7}")
print("-"*64)
tot = sum(sum(v) for v in by.values())
for a, v in sorted(by.items(), key=lambda kv: -sum(kv[1])):
    print(f"{a:>22} {len(v):>4} {statistics.median(v):>8.0f} {statistics.mean(v):>8.0f} {sum(v):>9} {100*sum(v)/tot:>6.1f}%")
print(f"{'TOTAL':>22} {len(t):>4} {'':>8} {'':>8} {tot:>9}")
