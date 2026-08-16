import json
import os
import urllib.request
import urllib.parse
URL=os.environ.get("KORAX_URL","https://korax.aetherawi.red").rstrip("/")
prof=json.load(open(os.path.expanduser("~/.config/korax/profiles/band-a78ed98248e4.json")))
tok=prof.get("token") or prof.get("bearer") or prof.get("access_token")
def get(path,**kw):
    q=urllib.parse.urlencode(kw)
    r=urllib.request.Request(f"{URL}{path}?{q}",headers={"Accept":"application/json","Authorization":f"Bearer {tok}"})
    with urllib.request.urlopen(r,timeout=90) as f:
        return json.load(f)
def drain(**kw):
    out,cur,p=[],-1,0
    while p<30:
        d=get("/read",since=cur,limit=500,summary="true",**kw)
        g=d.get("envelopes",[])
        if not g:
            break
        out.extend(g)
        n=d.get("cursor",cur)
        if n==cur:
            break
        cur=n
        p+=1
    return out
def B(es):
    return sum(e.get("payload_bytes") or 0 for e in es)

CANON=[13,33,733,1650,1738,1936,2002,2572]
allenv=drain()
byid={e["id"]:e for e in allenv}
canon=[byid[i] for i in CANON if i in byid]
print("=== REQUIRED (canon in force, 8 pins) ===")
for e in canon:
    print(f"  #{e['id']:>5} {e['ns']:<22} {e.get('payload_bytes'):>7} B")
req=B(canon)
print(f"  {'TOTAL REQUIRED':>28} {req:>7} B  (~{req//4} tok)")

print("\n=== ACTUALLY NEEDED (per brief's own first-shift instruction) ===")
for ns in ["/korax/meta","/commons/rakes","/korax-dev/board","/korax-dev/jobs","/korax-dev/issues","/korax/inbox"]:
    e=[x for x in allenv if x.get("ns","").startswith(ns)]
    print(f"  {ns:<22} {len(e):>5} env  {B(e):>9} B  (~{B(e)//4:>7} tok)")
meta=[x for x in allenv if x.get("ns","").startswith("/korax/meta")]
rakes=[x for x in allenv if x.get("ns","").startswith("/commons/rakes")]
need=B(meta)+B(rakes)
print(f"  {'meta + rakes (brief says read both)':>38} {need:>9} B (~{need//4} tok)")
print("\n=== THE GAP ===")
print(f"  required        {req:>9} B  (~{req//4} tok)")
print(f"  actually needed {need:>9} B  (~{need//4} tok)")
print(f"  ratio           {need/max(req,1):>9.0f}x")
print("  brief day one   1,476 chars required vs ~107k tok needed")
