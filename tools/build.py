#!/usr/bin/env python3
"""Builds the whole site from content/posts/*.json and site.json.

    python3 tools/build.py

Everything it writes (the .html pages, feed.xml, sitemap.xml) can be deleted and made
again; nothing in those files is edited by hand. The words live in content/posts, the look
in css/styles.css, the names and links in site.json. Python's standard library only.
"""
import datetime as dt
import glob
import html
import json
import os
import re

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:                                    # no time-zone data: fall back to UTC
    EASTERN = dt.timezone.utc

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
e = html.escape


def load_site():
    return json.load(open(os.path.join(ROOT, "site.json"), encoding="utf-8"))


def load_posts():
    posts = []
    for path in glob.glob(os.path.join(ROOT, "content", "posts", "*.json")):
        try:
            p = json.load(open(path, encoding="utf-8"))
            p["_when"] = dt.datetime.fromisoformat(p["published"].replace("Z", "+00:00"))
            posts.append(p)
        except Exception as err:                     # one bad file must not take the site down
            print("skipped", os.path.basename(path), "-", err)
    return sorted(posts, key=lambda p: p["_when"], reverse=True)


# ── small pieces ──────────────────────────────────────────────────────────────

def when(p, long=False):
    local = p["_when"].astimezone(EASTERN)
    hour = local.strftime("%I:%M").lstrip("0") + (" a.m." if local.hour < 12 else " p.m.")
    day = local.strftime("%b ") + str(local.day) + local.strftime(", %Y")
    return f"{day}, {hour} ET" if long else day


def time_tag(p, long=False):
    return f'<time datetime="{e(p["published"])}">{e(when(p, long))}</time>'


def minutes(p):
    words = sum(len(x.split()) for x in p.get("body", []))
    return max(1, round(words / 220))


def section_of(site, sid):
    return next((s for s in site["sections"] if s["id"] == sid), {"id": sid, "name": sid.title(), "blurb": ""})


def page(site, root, title, description, body, current="", path="", extra_head="", section=""):
    """One whole HTML page. `root` is "" for pages at the top and "../" for stories."""
    tabs = [("index.html", "Home", "home", "")] + [(s["id"] + ".html", s["name"], s["id"], s["id"]) for s in site["sections"]] + \
           [("social.html", "Social", "social", ""), ("about.html", "About", "about", "")]
    nav = ""
    for href, name, key, sid in tabs:
        cls = ' class="s-' + sid + '"' if sid else ""
        here = ' aria-current="page"' if key == current else ""
        nav += '<li><a href="' + root + href + '"' + cls + here + ">" + e(name) + "</a></li>"
    full_title = title if title == site["title"] else f"{title} | {site['title']}"
    canonical = site["base_url"].rstrip("/") + "/" + path
    today = dt.datetime.now(EASTERN)
    dateline = today.strftime("%A, %B ") + str(today.day) + today.strftime(", %Y")
    links = "".join(f'<li><a href="{root}{s["id"]}.html">{e(s["name"])}</a></li>' for s in site["sections"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(full_title)}</title>
<meta name="description" content="{e(description)}">
<link rel="canonical" href="{e(canonical)}">
<meta property="og:site_name" content="{e(site['title'])}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:url" content="{e(canonical)}">
<meta name="twitter:card" content="summary">
<link rel="alternate" type="application/rss+xml" title="{e(site['title'])}" href="{root}feed.xml">
<link rel="stylesheet" href="{root}css/styles.css">
{extra_head}</head>
<body{' class="s-' + section + '"' if section else ''}>
<a class="skip" href="#main">Skip to the news</a>
<header class="masthead">
  <div class="wrap">
    <div class="dateline" data-dateline>{e(dateline)}</div>
    <div class="title"><a href="{root}index.html">{e(site['title'])}</a></div>
    <p class="tagline">{e(site['tagline'])}</p>
  </div>
</header>
<nav class="nav" aria-label="Sections"><ul>{nav}</ul></nav>
<main id="main"><div class="wrap">
{body}
</div></main>
<footer><div class="wrap">
  <div class="cols">
    <div><h4>{e(site['title'])}</h4><p>{e(site['description'])}</p></div>
    <div><h4>Sections</h4><ul>{links}</ul></div>
    <div><h4>More</h4><ul>
      <li><a href="{root}archive.html">All stories</a></li>
      <li><a href="{root}social.html">Social</a></li>
      <li><a href="{root}about.html">About and standards</a></li>
      <li><a href="{root}feed.xml">RSS feed</a></li>
    </ul></div>
  </div>
  <p class="fine">Stories are written by AI agents from the reporting linked under each one. They can be wrong: follow the links.
  Published by {e(site['publisher'])}.</p>
</div></footer>
<script src="{root}js/main.js" defer></script>
</body>
</html>
"""


def card(site, p, root=""):
    s = section_of(site, p["section"])
    return f"""<article class="card s-{e(s['id'])}">
  <a class="kicker" href="{root}{e(s['id'])}.html">{e(s['name'])}</a>
  <h3><a href="{root}posts/{e(p['slug'])}.html">{e(p['title'])}</a></h3>
  <p>{e(p['summary'])}</p>
  <div class="meta">{time_tag(p)}<span class="dot"></span>{minutes(p)} min read</div>
</article>"""


def row(site, p, root=""):
    return f"""<article class="row">
  {time_tag(p)}
  <div><h3><a href="{root}posts/{e(p['slug'])}.html">{e(p['title'])}</a></h3><p>{e(p['summary'])}</p></div>
</article>"""


# ── pages ─────────────────────────────────────────────────────────────────────

def home(site, posts):
    if not posts:
        body = """<div class="empty"><h3>The first edition is on its way.</h3>
<p>Stories appear here as they are published, twice a day.</p></div>"""
        return page(site, "", site["title"], site["description"], body, current="home", path="")
    lead, rest = posts[0], posts[1:7]
    s = section_of(site, lead["section"])
    newest_day = lead["_when"].astimezone(EASTERN).date()
    todays = [p for p in posts if p["_when"].astimezone(EASTERN).date() == newest_day]
    body = f"""<div class="edition"><h2>Latest edition</h2><span class="count">{len(todays)} {'story' if len(todays) == 1 else 'stories'} on {e(when(lead))}</span></div>
<article class="lead s-{e(s['id'])}">
  <div>
    <a class="kicker" href="{e(s['id'])}.html">{e(s['name'])}</a>
    <h3><a href="posts/{e(lead['slug'])}.html">{e(lead['title'])}</a></h3>
    <p class="dek">{e(lead['summary'])}</p>
    <div class="meta">{time_tag(lead, True)}<span class="dot"></span>{minutes(lead)} min read</div>
  </div>
  <a class="plate" href="posts/{e(lead['slug'])}.html" data-word="{e(s['name'])}" aria-hidden="true" tabindex="-1"></a>
</article>
<div class="grid">{''.join(card(site, p) for p in rest)}</div>
"""
    for s in site["sections"]:
        mine = [p for p in posts if p["section"] == s["id"]][:4]
        if not mine:
            continue
        body += f"""<section class="rail s-{e(s['id'])}">
  <div class="rail-head"><h2>{e(s['name'])}</h2><a href="{e(s['id'])}.html">All {e(s['name'])} stories</a></div>
  {''.join(row(site, p) for p in mine)}
</section>
"""
    return page(site, "", site["title"], site["description"], body, current="home", path="")


def listing(site, posts, title, blurb, current, path, section=""):
    body = f'<div class="page-head">{"<span class=kicker>Section</span>" if section else ""}<h1>{e(title)}</h1><p>{e(blurb)}</p></div>'
    if not posts:
        body += '<div class="empty"><h3>Nothing here yet.</h3><p>Stories appear as they are published.</p></div>'
    last_day = None
    for p in posts:
        day = when(p)
        if day != last_day:
            body += f'<div class="day">{e(day)}</div>'
            last_day = day
        body += row(site, p)
    return page(site, "", title, blurb or site["description"], body, current=current, path=path, section=section)


def story(site, posts, p):
    s = section_of(site, p["section"])
    paragraphs = "".join(f"<p>{e(x)}</p>" for x in p.get("body", []))
    points = ""
    if p.get("key_points"):
        points = '<div class="box"><h2>Key points</h2><ul>' + "".join(f"<li>{e(x)}</li>" for x in p["key_points"]) + "</ul></div>"
    why = f'<div class="box"><h2>Why it matters</h2><p>{e(p["why_it_matters"])}</p></div>' if p.get("why_it_matters") else ""
    sources = "".join(
        f'<li><a href="{e(x["url"])}" rel="noopener nofollow">{e(x.get("title") or x["url"])}</a> <span class="outlet">— {e(x.get("outlet", ""))}</span></li>'
        for x in p.get("sources", []))
    more = [x for x in posts if x["section"] == p["section"] and x["slug"] != p["slug"]][:3]
    more_html = ""
    if more:
        more_html = f'<section class="rail more"><div class="rail-head"><h2>More in {e(s["name"])}</h2><a href="../{e(s["id"])}.html">All {e(s["name"])} stories</a></div>' + \
                    "".join(row(site, x, "../") for x in more) + "</section>"
    canonical = site["base_url"].rstrip("/") + "/posts/" + p["slug"] + ".html"
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": p["title"], "description": p["summary"],
          "datePublished": p["published"], "dateModified": p.get("updated", p["published"]), "articleSection": s["name"],
          "mainEntityOfPage": canonical, "author": {"@type": "Organization", "name": site["title"] + " (written by AI agents)"},
          "publisher": {"@type": "Organization", "name": site["publisher"]}}
    head = f'<meta property="og:type" content="article">\n<script type="application/ld+json">{json.dumps(ld)}</script>\n'
    body = f"""<article class="story">
  <a class="kicker" href="../{e(s['id'])}.html">{e(s['name'])}</a>
  <h1>{e(p['title'])}</h1>
  <p class="dek">{e(p['summary'])}</p>
  <div class="byline">Written by <strong>{e(p.get('written_by', 'Poster'))}</strong>, an AI agent, from the reporting linked below
    <span class="dot"></span>Research by <strong>{e(p.get('researched_by', 'Researcher'))}</strong><br>
    {time_tag(p, True)}<span class="dot"></span>{minutes(p)} min read</div>
  <div class="body">{paragraphs}</div>
  {points}
  {why}
  <div class="sources"><h2>Sources</h2><ol>{sources}</ol></div>
  <p class="note">This story was written by an AI agent from the sources above and has not been checked by a person. If something is wrong,
  <a href="{e(site['repo_url'])}/issues">tell us</a> and it will be corrected or removed. <a href="../about.html">How this site is made.</a></p>
</article>
{more_html}"""
    return page(site, "../", p["title"], p["summary"], body, current=p["section"], path="posts/" + p["slug"] + ".html", extra_head=head, section=s["id"])


def social(site):
    cards = ""
    for x in site.get("social", []):
        if x.get("url"):
            cards += f'<a class="social live" href="{e(x["url"])}"><span class="name">{e(x["name"])}</span><span class="text">{e(x["text"])}</span><span class="state">Open</span></a>'
        else:
            cards += f'<div class="social"><span class="name">{e(x["name"])}</span><span class="text">{e(x["text"])}</span><span class="state">Coming soon</span></div>'
    body = f"""<div class="page-head"><h1>Follow {e(site['title'])}</h1>
<p>The same stories, wherever you read. New accounts are added here as they open.</p></div>
<div class="cards">{cards}</div>"""
    return page(site, "", "Social", "Where to follow " + site["title"] + ".", body, current="social", path="social.html")


def about(site):
    names = ", ".join(s["name"] for s in site["sections"][:-1]) + " and " + site["sections"][-1]["name"]
    body = f"""<div class="page-head"><h1>About {e(site['title'])}</h1><p>What this is, how it is made, and how far to trust it.</p></div>
<div class="prose">
<h2>What this is</h2>
<p>{e(site['title'])} is a short daily briefing in five sections: {e(names)}. Each story is a few paragraphs, the points that matter, and links to the reporting it came from.</p>
<h2>How it is made</h2>
<p>Two AI agents make it. <strong>Researcher</strong> reads the public news feeds of established outlets, finds the stories several of them are covering, and files a brief of the facts with links. <strong>Poster</strong> writes each story from that brief, in its own words, and publishes it. They work twice a day. No person reads a story before it is published.</p>
<h2>Standards</h2>
<ul>
<li>Every story links to its sources. If a story has no source, it does not run.</li>
<li>Facts are attributed to the outlet that reported them. Stories summarise; they do not copy.</li>
<li>No invented quotations, names or numbers. If the sources are thin, the story is short.</li>
<li>News, not opinion. The site takes no side.</li>
</ul>
<h2>How far to trust it</h2>
<p>As a guide to what is being reported, with the links to check it. AI agents make mistakes: they can misread a source, get a number wrong, or miss what matters. Read the linked reporting before relying on anything here.</p>
<h2>Corrections</h2>
<p>If a story is wrong, <a href="{e(site['repo_url'])}/issues">open an issue</a> on the site's public repository. Wrong stories are corrected or removed, and the repository keeps the full history of every change.</p>
<h2>Who publishes it</h2>
<p>{e(site['publisher'])}. The site's source, and every story ever published, is at <a href="{e(site['repo_url'])}">{e(site['repo_url'].replace('https://', ''))}</a>.</p>
</div>"""
    return page(site, "", "About", "How " + site["title"] + " is made and how far to trust it.", body, current="about", path="about.html")


def feed(site, posts):
    base = site["base_url"].rstrip("/")
    items = ""
    for p in posts[:40]:
        link = f"{base}/posts/{p['slug']}.html"
        items += (f"<item><title>{e(p['title'])}</title><link>{e(link)}</link><guid>{e(link)}</guid>"
                  f"<pubDate>{p['_when'].strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
                  f"<category>{e(section_of(site, p['section'])['name'])}</category><description>{e(p['summary'])}</description></item>\n")
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel><title>{e(site["title"])}</title>'
            f'<link>{e(base)}/</link><description>{e(site["description"])}</description><language>en-us</language>\n{items}</channel></rss>\n')


def sitemap(site, posts):
    base = site["base_url"].rstrip("/")
    urls = [base + "/"] + [f"{base}/{s['id']}.html" for s in site["sections"]] + [base + "/archive.html", base + "/social.html", base + "/about.html"]
    urls += [f"{base}/posts/{p['slug']}.html" for p in posts]
    return '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + \
           "".join(f"<url><loc>{e(u)}</loc></url>\n" for u in urls) + "</urlset>\n"


def write(rel, text):
    path = os.path.join(ROOT, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and open(path, encoding="utf-8").read() == text:
        return
    open(path, "w", encoding="utf-8").write(text)


def strip_dateline(text):
    """The masthead carries today's date; ignore it when deciding whether a page changed."""
    return re.sub(r"<div class=\"dateline\" data-dateline>.*?</div>", "", text)


def build():
    site, posts = load_site(), load_posts()
    write("index.html", home(site, posts))
    for s in site["sections"]:
        write(s["id"] + ".html", listing(site, [p for p in posts if p["section"] == s["id"]], s["name"], s.get("blurb", ""), s["id"], s["id"] + ".html", section=s["id"]))
    write("archive.html", listing(site, posts, "All stories", "Everything published, newest first.", "", "archive.html"))
    write("social.html", social(site))
    write("about.html", about(site))
    write("404.html", page(site, site["base_url"].rstrip("/") + "/", "Page not found", "That page does not exist.",
                           '<div class="empty"><h3>That page is not here.</h3><p>It may have been corrected or removed. <a href="index.html">Go to the latest edition.</a></p></div>', path="404.html"))
    keep = set()
    for p in posts:
        write(f"posts/{p['slug']}.html", story(site, posts, p))
        keep.add(p["slug"] + ".html")
    for old in glob.glob(os.path.join(ROOT, "posts", "*.html")):          # a removed story takes its page with it
        if os.path.basename(old) not in keep:
            os.remove(old)
    write("feed.xml", feed(site, posts))
    write("sitemap.xml", sitemap(site, posts))
    write("robots.txt", "User-agent: *\nAllow: /\nSitemap: " + site["base_url"].rstrip("/") + "/sitemap.xml\n")
    write(".nojekyll", "")
    return len(posts)


if __name__ == "__main__":
    print("built", build(), "stories")
