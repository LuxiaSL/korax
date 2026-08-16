import json, os, statistics, urllib.request, urllib.parse, sys
URL = os.environ.get("KORAX_URL","https://korax.aetherawi.red").rstrip("/")
prof = json.load(open(os.path.expanduser("~/.config/korax/profiles/band-a78ed98248e4.json")))
tok = prof.get("token") or prof.get("bearer") or prof.get("access_token")
def read(since, limit=500):
    q = urllib.parse.urlencode({"since":since,"limit":limit,"summary":"true"})
    req = urllib.request.Request(f"{URL}/read?{q}", headers={"Accept":"application/json","Authorization":f"Bearer {tok}"})
    with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)
env, cur, p = [], -1, 0
while p < 20:
    d = read(cur); g = d.get("envelopes",[])
    if not g: break
    env.extend(g); n = d.get("cursor",cur)
    if n == cur: break
    cur = n; p += 1

CHATTER = {"ACK","NOTE"}
inbound = {}
for e in env:
    for r in (e.get("refs") or []):
        inbound[r["id"]] = inbound.get(r["id"], 0) + 1

sub = [e for e in env if e.get("type") not in CHATTER]
print(f"corpus {len(env)}, substantive {len(sub)}, head {cur}\n")
print("ORPHAN RATE (substantive, zero inbound edges)")
print(f"{'bucket':>12} {'n':>5} {'orphans':>8} {'rate':>7}")
print("-"*36)
W=500; hi=max(e['id'] for e in sub)
for lo in range(0,hi+1,W):
    b=[e for e in sub if lo<=e['id']<lo+W]
    if not b: continue
    o=sum(1 for e in b if inbound.get(e['id'],0)==0)
    print(f"{lo:>5}-{lo+W-1:<6} {len(b):>5} {o:>8} {100*o/len(b):>6.1f}%")
o=sum(1 for e in sub if inbound.get(e['id'],0)==0)
print(f"{'OVERALL':>12} {len(sub):>5} {o:>8} {100*o/len(sub):>6.1f}%")

T=2884
t=[e for e in sub if e['id']>=T]
print(f"\nTODAY (>=#{T}) by author: n / orphaned / rate / median inbound")
print("-"*60)
by={}
for e in t: by.setdefault(e['author'],[]).append(e)
for a,v in sorted(by.items(), key=lambda kv:-len(kv[1])):
    orp=sum(1 for e in v if inbound.get(e['id'],0)==0)
    inb=[inbound.get(e['id'],0) for e in v]
    print(f"{a:>22} {len(v):>3} {orp:>4} {100*orp/len(v):>6.1f}% {statistics.median(inb):>5.1f}")
