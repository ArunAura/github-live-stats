#!/usr/bin/env python3
"""Refresh the original SVG dashboard with live GitHub data for ArunAura."""
import json, os, re, urllib.request, urllib.error
from datetime import datetime, timezone
from pathlib import Path

USER = os.getenv("GITHUB_USERNAME", "ArunAura")
TOKEN = os.getenv("GH_STATS_TOKEN") or os.getenv("GITHUB_TOKEN")
ROOT = Path(__file__).resolve().parent
TEMPLATE = ROOT / "stats-template.svg"
OUTPUT = ROOT / "github-stats.svg"

if not TOKEN:
    raise SystemExit("Missing GH_STATS_TOKEN secret. See README.md.")

def request(url, method="GET", data=None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method, headers={
        "Authorization": f"Bearer {TOKEN}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "Content-Type": "application/json",
        "User-Agent": "ArunAura-live-stats"
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        detail=e.read().decode(errors="replace")
        raise RuntimeError(f"GitHub API returned HTTP {e.code}: {detail[:500]}") from e

def graph(query, variables=None):
    result=request("https://api.github.com/graphql", "POST", {"query":query,"variables":variables or {}})
    if result.get("errors"):
        raise RuntimeError("GitHub GraphQL error: " + json.dumps(result["errors"])[:1000])
    return result["data"]

def xml_escape(s):
    return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')

def replace_text(svg, old, new, count=1):
    # Replace only visible text nodes, preserving the original SVG markup and animation.
    pattern = r'(?<=>)' + re.escape(str(old)) + r'(?=</text>)'
    result, n = re.subn(pattern, lambda _: xml_escape(new), svg, count=count)
    if n == 0:
        print(f"Warning: couldn't find SVG text value {old!r}")
    return result

def replace_first(pattern, repl, svg):
    result,n=re.subn(pattern,repl,svg,count=1)
    if not n: print(f"Warning: SVG pattern not found: {pattern[:80]}")
    return result

# Basic public profile and repository metrics
profile=request(f"https://api.github.com/users/{USER}")
repos=[]
page=1
while True:
    batch=request(f"https://api.github.com/users/{USER}/repos?per_page=100&page={page}&type=owner&sort=updated")
    if not batch: break
    repos.extend(r for r in batch if not r.get("fork") and not r.get("archived"))
    if len(batch)<100: break
    page+=1
public_repos=profile.get("public_repos",0)
stars=sum(r.get("stargazers_count",0) for r in repos)
followers=profile.get("followers",0)

# Contribution calendar, weekday totals, current streak and longest streak
query="query($login:String!){ user(login:){ contributionsCollection { contributionCalendar { totalContributions weeks { contributionDays { contributionCount date weekday } } } } } }"
data=graph(query,{"login":USER})
user=data.get("user")
if not user: raise RuntimeError(f"GitHub user {USER!r} was not found or isn't visible to this token.")
calendar=user["contributionsCollection"]["contributionCalendar"]
total_contrib=calendar["totalContributions"]
days=[day for week in calendar["weeks"] for day in week["contributionDays"]]
# GitHub weekday enum: Sunday=0 ... Saturday=6; dashboard labels Monday first.
weekday_names=["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
weekday_counts=[sum(d["contributionCount"] for d in days if d["weekday"]==i) for i in [1,2,3,4,5,6,0]]
most_active=weekday_names[max(range(7),key=lambda i:weekday_counts[i])] if any(weekday_counts) else "—"
# Streaks based on days with at least one contribution; include today if active, otherwise count from yesterday.
by_date={d["date"]:d["contributionCount"] for d in days}
today=datetime.now(timezone.utc).date()
from datetime import timedelta
current=0
cursor=today
if by_date.get(cursor.isoformat(),0)==0: cursor-=timedelta(days=1)
while by_date.get(cursor.isoformat(),0)>0:
    current+=1; cursor-=timedelta(days=1)
longest=0; run=0; best_start=best_end=None; run_start=None
for d in days:
    date=d["date"]
    if d["contributionCount"]>0:
        if run==0: run_start=date
        run+=1
        if run>longest: longest=run; best_start=run_start; best_end=date
    else: run=0; run_start=None

def short_date(iso):
    return datetime.strptime(iso,"%Y-%m-%d").strftime("%b %-d") if os.name!="nt" else datetime.strptime(iso,"%Y-%m-%d").strftime("%b %#d")
longest_label=(f"{short_date(best_start)} - {short_date(best_end)}" if best_start and best_end else "No streak yet")

# Language data: repo count is by each repository's primary language; code-size uses GitHub language byte counts.
repo_lang={}
code_lang={}
for repo in repos:
    lang=repo.get("language")
    if lang: repo_lang[lang]=repo_lang.get(lang,0)+1
    try:
        langs=request(repo["languages_url"])
        for name,amount in langs.items(): code_lang[name]=code_lang.get(name,0)+amount
    except Exception as exc:
        print(f"Warning: couldn't fetch languages for {repo.get('full_name')}: {exc}")

def top_items(counter, n=5):
    return sorted(counter.items(), key=lambda x:(-x[1],x[0]))[:n]
repo_top=top_items(repo_lang)
code_top=top_items(code_lang)
COLORS={"HTML":"#e34c26","TypeScript":"#3178c6","JavaScript":"#f1e05a","CSS":"#8957e5","SCSS":"#c6538c","Python":"#3572A5","Java":"#b07219","C++":"#f34b7d","C":"#555555","C#":"#178600","Go":"#00ADD8","Jupyter Notebook":"#DA5B0B","Dart":"#00B4AB","Kotlin":"#A97BFF","PHP":"#4F5D95","Ruby":"#701516","Rust":"#dea584","Shell":"#89e051","Vue":"#41b883","Svelte":"#ff3e00"}
FALLBACK=["#e34c26","#3178c6","#f1e05a","#8957e5","#c6538c"]

def fmt_bytes(n):
    if n>=1_000_000: return f"{n/1_000_000:.1f}M"
    if n>=1000: return f"{n/1000:.0f}K"
    return str(n)

svg=TEMPLATE.read_text()
svg=replace_text(svg,"232",total_contrib)
svg=replace_text(svg,"0",current,1)
svg=replace_text(svg,"8",longest,1)
svg=replace_text(svg,"Oct 2 - Oct 9",longest_label)
svg=replace_text(svg,"most active: Sun",f"most active: {most_active}")
svg=replace_text(svg,"21",len(repos))
svg=replace_text(svg,"608K",fmt_bytes(sum(code_lang.values())))
svg=replace_text(svg,"22",public_repos)
svg=replace_text(svg,"126",stars)
svg=replace_text(svg,"52",followers)
svg=replace_text(svg,"live from GitHub - updates every day",f"@{USER} - refreshed {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

# Update the weekday bar heights and labels while retaining the original positions/colors/animations.
maxv=max(weekday_counts) or 1
for i,(label,value) in enumerate(zip(weekday_names,weekday_counts)):
    x=563+62*i
    # Bar baseline is y=232; available height is 100.
    height=round(100*value/maxv,1); y=round(232-height,1)
    # Change the bar's static geometry and both animation endpoints.
    bar_pattern=rf'<rect x="{x-19:.1f}" y="[^"]+" width="38" height="[^"]+" rx="6" fill="(?:url\(#bar\)|#ffffff)"><animate attributeName="height" values="0;0;[^"]+"'
    # x values in source are integer x positions for bars, while text labels use decimal centers.
    bx=544+62*i
    bar_pattern=rf'(<rect x="{bx}" y=")[^"]+(" width="38" height=")[^"]+(" rx="6" fill="(?:url\(#bar\)|#ffffff)"><animate attributeName="height" values="0;0;)[^"]+'
    svg=re.sub(bar_pattern,lambda m:m.group(1)+str(y)+m.group(2)+str(height)+m.group(3)+str(height),svg,count=1)
    # y animation follows bar top; replace first relevant y animation after this bar
    start=svg.find(f'<rect x="{bx}"')
    if start>=0:
        end=svg.find('</rect>',start)
        chunk=svg[start:end]
        chunk=re.sub(r'(<animate attributeName="y" values="232;232;)[^"]+',lambda m:m.group(1)+str(y),chunk,count=1)
        svg=svg[:start]+chunk+svg[end:]
    svg=replace_text(svg,["36","22","10","32","42","14","76"][i],value,1)

# Replace each language label/value in its existing five rows. Keep colors/style and update matching donut slices.
def update_lang_section(items, center_x, row_x, value_x, old_names, old_values, section):
    global svg
    circumference=402.12
    # map the five current rows by their visible labels and update first occurrence within the section range
    start=svg.find(section)
    if start<0: return
    end=svg.find('</g><rect x="516"' if section=="Top Languages by Repository" else '<rect x="28" y="570"',start)
    if end<0: end=len(svg)
    part=svg[start:end]
    # The chart region includes donut arcs before the labels. Replace the text nodes by row position.
    rows=items[:5]
    total=sum(v for _,v in rows) or 1
    # replace label/value text strings in this section, using known old labels in their occurrence order
    for i in range(5):
        new_name,new_value=rows[i] if i<len(rows) else ("No data",0)
        old_name=old_names[i]
        old_val=old_values[i]
        # only in this section and after section heading; each language text label occurs once here
        part=replace_text(part,old_name,new_name,1)
        percent=100*new_value/total if total else 0
        part=replace_text(part,old_val,f"{percent:.1f}%",1)
    # Replace all arc geometry associated with this donut, preserving circle track and stroke colors.
    arc_index=0
    pattern=r'<circle cx="'+str(center_x)+r'" cy="442" r="64" fill="none" stroke="(?!#1b2438)[^"]+" stroke-width="24" stroke-dasharray="[^"]+" stroke-dashoffset="[^"]+" transform="rotate\(-90 '+str(center_x)+r' 442\)"><animate attributeName="stroke-dasharray" values="0 402\.12;0 402\.12;[^"]+"'
    matches=list(re.finditer(pattern,part))
    offset=0.0
    for i,m in enumerate(matches):
        value=rows[i][1] if i<len(rows) else 0
        arc=round(circumference*value/total,2) if total else 0
        remainder=round(circumference-arc,2)
        dash=f"{arc:.2f} {remainder:.2f}"
        off=f"-{offset:.2f}"
        old=m.group(0)
        new=re.sub(r'stroke-dasharray="[^"]+"',f'stroke-dasharray="{dash}"',old,count=1)
        new=re.sub(r'stroke-dashoffset="[^"]+"',f'stroke-dashoffset="{off}"',new,count=1)
        new=re.sub(r'values="0 402\.12;0 402\.12;[^"]+"',f'values="0 402.12;0 402.12;{dash}"',new,count=1)
        part=part.replace(old,new,1)
        offset+=arc
    svg=svg[:start]+part+svg[end:]

update_lang_section(repo_top,136,256,474,["HTML","TypeScript","JavaScript","CSS","SCSS"],["66.7%","14.3%","9.5%","4.8%","4.8%"],"Top Languages by Repository")
update_lang_section(code_top,624,744,946,["TypeScript","HTML","JavaScript","CSS","SCSS"],["34.1%","27.5%","24.9%","10.3%","3.2%"],"Top Languages by Code Size")

# Update color dots/text values for the new language names using their mapped colors.
for center_x,items,labels_x,values_x in [(136,repo_top,256,474),(624,code_top,744,946)]:
    for i in range(5):
        name=items[i][0] if i<len(items) else "No data"
        color=COLORS.get(name,FALLBACK[i])
        y=375+34*i
        # Set color on row dot and percentage text; safe scoped to the appropriate row vicinity.
        svg=re.sub(rf'(<circle cx="{labels_x-16}" cy="{y}" r="6" fill=")[^"]+',lambda m:m.group(1)+color,svg,count=1)
        svg=re.sub(rf'(<text class="num" x="{values_x}" y="{y+5}" text-anchor="end" fill=")[^"]+',lambda m:m.group(1)+color,svg,count=1)

OUTPUT.write_text(svg)
print(f"Wrote {OUTPUT.name}: contributions={total_contrib}, repos={public_repos}, stars={stars}, followers={followers}")
