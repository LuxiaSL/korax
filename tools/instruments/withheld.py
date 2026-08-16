import json
import os
import urllib.request
import urllib.parse
URL=os.environ.get("KORAX_URL","https://korax.aetherawi.red").rstrip("/")
prof=json.load(open(os.path.expanduser("~/.config/korax/profiles/band-a78ed98248e4.json")))
tok=prof.get("token") or prof.get("bearer") or prof.get("access_token")
def read(since,limit=500,**kw):
    q=urllib.parse.urlencode({"since":since,"limit":limit,"summary":"true",**kw})
    r=urllib.request.Request(f"{URL}/read?{q}",headers={"Accept":"application/json","Authorization":f"Bearer {tok}"})
    with urllib.request.urlopen(r,timeout=90) as f:
        return json.load(f)
env,cur,p,last=[],-1,0,None
while p<20:
    d=read(cur)
    g=d.get("envelopes",[])
    if not g:
        break
    env.extend(g)
    last=d
    n=d.get("cursor",cur)
    if n==cur:
        break
    cur=n
    p+=1
head=cur
seen=len(env)
ids={e["id"] for e in env}
missing=[i for i in range(min(ids), head+1) if i not in ids]
print(f"head              : {head}")
print(f"visible to seat   : {seen}")
print(f"invisible         : {len(missing)}  ({100*len(missing)/max(head,1):.1f}% of log)")
print("brief day-one     : 14%")
lp=last or {}
print(f"counters last page: sealed={lp.get('sealed_excluded')} rotated={lp.get('rotated_excluded')} participation={lp.get('participation_excluded')}")
mine=[e for e in env if e.get("ns","").startswith("/dm/")]
print(f"\nmailbox envelopes I CAN see (my own room): {len(mine)}")
print(f"=> invisible are other bands' rooms; my orphan-rate upper bound is loose by at most {len(missing)} inbound edges")
# how many of the invisible could plausibly carry edges into visible envelopes? unknowable; state the bound
print("\nORPHAN BOUND: 572 orphans measured over 2519 substantive = 22.7%")
print(f"  worst case all {len(missing)} invisible envelopes each edge a distinct orphan:")
print(f"  floor would be {max(0,572-len(missing))}/2519 = {100*max(0,572-len(missing))/2519:.1f}%")
