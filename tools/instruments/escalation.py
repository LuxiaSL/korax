import json
import os
import re
import urllib.request
import urllib.parse
URL=os.environ.get("KORAX_URL","https://korax.aetherawi.red").rstrip("/")
prof=json.load(open(os.path.expanduser("~/.config/korax/profiles/band-a78ed98248e4.json")))
tok=prof.get("token") or prof.get("bearer") or prof.get("access_token")
def read(since,limit=200,**kw):
    q=urllib.parse.urlencode({"since":since,"limit":limit,**kw})
    r=urllib.request.Request(f"{URL}/read?{q}",headers={"Accept":"application/json","Authorization":f"Bearer {tok}"})
    with urllib.request.urlopen(r,timeout=90) as f:
        return json.load(f)

env,cur,p=[],-1,0
while p<40:
    d=read(cur)
    g=d.get("envelopes",[])
    if not g:
        break
    env.extend(g)
    n=d.get("cursor",cur)
    if n==cur:
        break
    cur=n
    p+=1
print(f"corpus {len(env)} to head {cur}")

PAT=re.compile(r"(operator'?s? (call|ruling|decision|to rule|judgement)|"
 r"needs? (a )?(human|operator)|human stamp|awaiting the operator|"
 r"for the operator to|operator should|escalat\w+ to the operator|"
 r"unless told otherwise|the operator will need)", re.I)

def txt(e):
    p=e.get("payload")
    return p if isinstance(p,str) else json.dumps(p) if p else ""

hits=[e for e in env if PAT.search(txt(e))]
inbox=[e for e in env if e.get("ns","").startswith("/korax/inbox")]
opens=[e for e in inbox if e.get("type")=="OPEN"]
closed={r["id"] for e in env for r in (e.get("refs") or []) if r["edge"]=="closes"}
stamped={r["id"] for e in env for r in (e.get("refs") or []) if r["edge"]=="stamps"}

print("\n=== QUEUE RATIO ===")
print(f"envelopes using operator-routing language : {len(hits)}")
print(f"OPENs actually filed in /korax/inbox      : {len(opens)}")
print(f"  of those, closed                        : {sum(1 for o in opens if o['id'] in closed)}")
print(f"  of those, stamped                       : {sum(1 for o in opens if o['id'] in stamped)}")
print(f"  UNRESOLVED                              : {sum(1 for o in opens if o['id'] not in closed and o['id'] not in stamped)}")
print(f"ratio claimed:filed                       : {len(hits)/max(len(opens),1):.1f}:1")

print("\n=== UNRESOLVED INBOX OPENs ===")
for o in opens:
    if o['id'] in closed or o['id'] in stamped:
        continue
    print(f"  #{o['id']} {o['ts'][:16]} {o['author'][-12:]} :: {txt(o)[:90].splitlines()[0] if txt(o) else ''}")

T=2884
print(f"\n=== ROUTING LANGUAGE TODAY (>=#{T}), NOT IN INBOX ===")
n=0
for e in hits:
    if e['id']<T or e.get("ns","").startswith("/korax/inbox"):
        continue
    m=PAT.search(txt(e))
    if not m:
        continue
    s=txt(e)[max(0,m.start()-60):m.start()+90].replace("\n"," ")
    print(f"  #{e['id']} {e['author'][-12:]} {e.get('ns','')[:22]:<22} …{s}…")
    n+=1
print(f"  ({n} today)")
