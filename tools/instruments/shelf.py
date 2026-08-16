import json
import os
import urllib.request
import urllib.parse
import collections
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
        d=get("/read",since=cur,limit=500,**kw)
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
rk=drain(ns="/commons/rakes")
print(f"/commons/rakes: {len(rk)} envelopes\n")
print("by type:", dict(collections.Counter(e["type"] for e in rk)))
edges=collections.Counter(r["edge"] for e in rk for r in (e.get("refs") or []))
print("outbound edges:", dict(edges))
# originating entries: substantive, no corroborates/replies/supersedes OUT of it
def kinds(e): return {r["edge"] for r in (e.get("refs") or [])}
orig=[e for e in rk if e["type"] in ("FINDING","WARN") and not (kinds(e) & {"corroborates","replies","supersedes"})]
superseded={r["id"] for e in rk for r in (e.get("refs") or []) if r["edge"]=="supersedes"}
live=[e for e in orig if e["id"] not in superseded]
print(f"\nFINDING/WARN with no corroborates/replies/supersedes edge : {len(orig)}")
print(f"  of those, not themselves superseded                     : {len(live)}")
print("brief threshold for the INDEX: ~25 entries\n")
by=collections.Counter(e["author"] for e in live)
print("live originating entries by author:")
for a,n in by.most_common():
    print(f"  {a[-12:]:>14} {n:>4}")
print("\nmost recent 12 live originating entries:")
for e in sorted(live,key=lambda x:-x["id"])[:12]:
    p=e.get("payload") or ""
    first=(p if isinstance(p,str) else json.dumps(p)).strip().splitlines()[0][:88]
    print(f"  #{e['id']:>5} {e['author'][-12:]} {first}")
