#!/usr/bin/env python3
"""The news desk: everything the two agents do to this site goes through here.

    Researcher                                   Poster
    ----------                                   ------
    research   read the outlets' feeds,          queue     the next brief waiting to be written
               group them into stories           publish   check a finished story, add it to the
    story      one story's sources, with the               site, rebuild, commit and push
               articles' own text                status    what has been published today
    brief      file the facts for one story

    python3 tools/newsdesk.py research
    python3 tools/newsdesk.py story --json '{"story": "A2"}'
    python3 tools/newsdesk.py brief --json '{"story": "A2", "angle": "...", "points": ["...", "..."]}'
    python3 tools/newsdesk.py queue
    python3 tools/newsdesk.py publish --json '{"brief": "...", "title": "...", "summary": "..."}' --content-file story.txt
    python3 tools/newsdesk.py status
    python3 tools/newsdesk.py unpublish --json '{"slug": "..."}'      (corrections: removes a story)

Each prints one JSON object. The desk does not trust the writer. A brief's facts must be in
the sources' text. A story must be about its brief, must not carry a name or a number the
sources lack, must not copy the sources' sentences, and must not say things they do not.
What fails is refused with the reason in plain words; a story refused four times is set
aside. Set NEWSDESK_NO_PUSH=1 to try things without touching GitHub.
Python's standard library only.
"""
import concurrent.futures as cf
import datetime as dt
import glob
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import build as site_build  # noqa: E402

DESK = os.path.join(ROOT, "desk")
POSTS = os.path.join(ROOT, "content", "posts")
LETTER = {"world": "W", "us": "U", "tech": "T", "ai": "A", "robotics": "R"}
WINDOW = {"robotics": 96, "ai": 48}                  # hours; slower beats look further back
AGENT = "Mozilla/5.0 (Macintosh) RostyslavDaily/1.0 (+https://github.com/Rostyslav296/rostyslav-daily)"

# Not news: live blogs, shopping, quizzes, columns, promotions.
SKIP = re.compile(r"\b(live updates?|live blog|as it happened|podcast|quiz|crossword|wordle|in pictures|photos of the|newsletter|"
                  r"opinion|editorial|hands[- ]on|how to watch|horoscope|recipe|obituar\w*|techcrunch mobility|on equity|week in review|"
                  r"what to watch|playlist|prime day|discount|deals?|cheaper|on sale|gift (cards?|ideas?|guide)|video friday|"
                  r"calling \w+ startups|exhibit at|predictions were wrong)\b|review:|letters?:|the download:|\blive\s*$|\$\d+ off|"
                  r"^the best\b|\bbest .* (of|for) 20\d\d|^last \d+ hours", re.I)
COLUMN = re.compile(r"\b(writes a columnist|columnist|opinion:|commentary|guest post|sponsored|in this episode|this week on)\b", re.I)
TECH_SUBJECT = re.compile(r"\b(AI|A\.I\.|software|apps?|chips?|semiconductor|Apple|Google|Microsoft|Amazon|Meta|Nvidia|OpenAI|Anthropic|Tesla|Samsung|"
                          r"startups?|cyber\w*|hack\w*|breach|data|phones?|iPhone|Android|devices?|internet|online|robots?|robotaxis?|EVs?|batter\w+|"
                          r"satellites?|cloud|privacy|encryption|antitrust|browser|social media|platforms?|streaming|quantum|broadband|5G|gadgets?|"
                          r"computing|computers?|laptops?|wearables?|drones?|crypto\w*|bitcoin|open source|developers?|tech)\b")
US_MARK = re.compile(r"\b(U\.S\.|US|USA|America|American|Americans|Trump|Congress|Senate|White House|Supreme Court|FBI|Pentagon|"
                     r"Republican|Democrat|Democrats|Republicans|federal|governor|California|Texas|Florida|New York|Washington|Tennessee|"
                     r"Ohio|Illinois|Pennsylvania|Michigan|Arizona|Virginia|Carolina|Massachusetts|Colorado|Oregon|Nevada)\b")
STOP = set("a an the and or but of to in on for with at by from as is are was were be been it its this that these those after over "
           "into about amid says say said new will would could may might has have had not no than more most up out off his her their "
           "he she they you we us our who what when where why how".split())
# Capitalised words that are not names, for the check that a story's names come from its sources.
COMMON = set("monday tuesday wednesday thursday friday saturday sunday january february march april may june july august september october "
             "november december the a an in on at for and but or of to by from with as is it its this that these those he she they his her their "
             "after before during according reports report reported says said u.s us american americans world news today week year president "
             "minister government company companies officials police court state national international one two three four five six seven eight "
             "nine ten first second third new why what when where how who which".split())


def now():
    return dt.datetime.now(dt.timezone.utc)


def read(path, default=None):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return default


def save(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    json.dump(data, open(tmp, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def clean(text, limit=None):
    """Feed text as plain text: tags and entities gone, whitespace single."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit and len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def norm(text):
    """Lower case, accents gone, curly apostrophes straight."""
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)).replace("’", "'")


def words(text):
    """A text's telling words: hyphens joined ("run-off" is "runoff"), small words dropped."""
    plain = re.sub(r"(?<=[a-z])[-‐‑](?=[a-z])", "", norm(text)).replace("'s", "")
    return {w for w in re.findall(r"[a-z0-9]+", plain) if w not in STOP and len(w) > 2}


def alike(a, b):
    a, b = words(a), words(b)
    return len(a & b) / max(1, min(len(a), len(b))) if a and b else 0.0


def same_story(a, b):
    """Two headlines tell one story when half their telling words match, or three of them do."""
    return alike(a, b) >= 0.5 or len(words(a) & words(b)) >= 3


def published_posts():
    return [p for p in (read(f) for f in glob.glob(os.path.join(POSTS, "*.json"))) if p]


def briefs(status=None):
    out = [b for b in (read(f) for f in sorted(glob.glob(os.path.join(DESK, "briefs", "*.json")))) if b]
    return [b for b in out if status is None or b.get("status") == status]


# ── research ──────────────────────────────────────────────────────────────────

def fetch(job):
    section, outlet, url = job
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=25).read()
        root = ET.fromstring(raw)
    except Exception as err:
        return section, outlet, None, f"{type(err).__name__}: {str(err)[:80]}"
    items = []
    for el in root.iter():
        if el.tag.split("}")[-1] not in ("item", "entry"):
            continue
        got = {}
        for child in el:
            tag = child.tag.split("}")[-1]
            if tag == "link":
                got["link"] = got.get("link") or (child.text or "").strip() or child.attrib.get("href", "")
            elif tag in ("title", "description", "summary", "pubDate", "published", "updated", "date"):
                got.setdefault(tag, child.text or "")
        title, link = clean(got.get("title")), (got.get("link") or "").strip()
        if not title or not link.startswith("http"):
            continue
        stamp = got.get("pubDate") or got.get("published") or got.get("date") or got.get("updated") or ""
        when = None
        try:
            when = parsedate_to_datetime(stamp) if "," in stamp else dt.datetime.fromisoformat(stamp.strip().replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=dt.timezone.utc)
        except Exception:
            pass
        items.append({"section": section, "outlet": outlet, "title": title, "url": link.split("#")[0],
                      "summary": clean(got.get("description") or got.get("summary"), 420), "when": when})
    return section, outlet, items, None


def place(items, among):
    """Which section a story belongs to. A specialist feed's word is taken (robotics, then AI,
    then tech). Between U.S. and World the feeds are little guide, since general feeds carry
    both: a story only U.S. desks carry is domestic; otherwise its own words decide."""
    for section in ("robotics", "ai"):
        if section in among:
            return section
    count = {s: sum(1 for x in items if x["section"] == s) for s in ("tech", "us", "world")}
    if count["tech"] and count["tech"] >= max(count["us"], count["world"]):
        return "tech"
    if count["us"] and not count["world"]:
        return "us"
    saying_us = sum(1 for x in items if US_MARK.search(x["title"] + " " + x["summary"]))
    in_headline = sum(1 for x in items if US_MARK.search(x["title"]))
    return "us" if in_headline * 2 >= len(items) or saying_us * 3 >= len(items) * 2 else "world"


def research(hours=36):
    """Read every feed, keep what is recent and is news, group the same story across outlets, rank, save."""
    feeds = read(os.path.join(ROOT, "tools", "feeds.json"), {})
    jobs = [(s, name, url) for s, lst in feeds.items() if not s.startswith("_") for name, url in lst]
    failed, items = [], []
    with cf.ThreadPoolExecutor(12) as pool:
        for section, outlet, got, err in pool.map(fetch, jobs):
            if err:
                failed.append(f"{outlet} ({section}): {err}")
                continue
            since = now() - dt.timedelta(hours=WINDOW.get(section, hours))
            items += [i for i in got if (i["when"] is None or i["when"] >= since) and not SKIP.search(i["title"])
                      and not COLUMN.search(i["title"] + " " + i["summary"])
                      and (section != "tech" or TECH_SUBJECT.search(i["title"] + " " + i["summary"]))]
    used = {s["url"] for p in published_posts() for s in p.get("sources", [])} | {s["url"] for b in briefs() for s in b.get("sources", [])}
    recent_titles = [p["title"] for p in published_posts()][-60:] + [b["working_title"] for b in briefs()][-60:]
    items = [i for i in items if i["url"] not in used and not any(alike(i["title"], t) >= 0.75 for t in recent_titles)]

    clusters, sections = [], []                      # the same story told by several outlets is one story
    oldest = now() - dt.timedelta(hours=200)
    for item in sorted(items, key=lambda i: i["when"] or oldest, reverse=True):
        at = next((n for n, c in enumerate(clusters) if any(x["url"] == item["url"] or same_story(item["title"], x["title"]) for x in c[:3])), None)
        if at is None:
            clusters.append([item]); sections.append({item["section"]})
            continue
        sections[at].add(item["section"])            # an outlet's AI feed and its main feed both carry an AI story
        if item["url"] not in {x["url"] for x in clusters[at]}:
            clusters[at].append(item)
    stories = []
    for c, among in zip(clusters, sections):
        outlets = sorted({x["outlet"] for x in c})
        newest = max((x["when"] for x in c if x["when"]), default=None)
        age = (now() - newest).total_seconds() / 3600 if newest else 30.0
        lead = max(c, key=lambda x: len(x["summary"]))
        stories.append({"section": place(c, among), "title": c[0]["title"], "summary": lead["summary"], "outlets": outlets, "age_hours": round(age, 1),
                        "score": round(3 * len(outlets) + max(0.0, 2.0 - age / 12), 2),
                        "sources": [{"outlet": x["outlet"], "title": x["title"], "url": x["url"], "summary": x["summary"]} for x in c[:5]]})
    result = {"made": now().isoformat(), "feeds_read": len(jobs) - len(failed), "feeds_failed": failed, "stories": []}
    for section in LETTER:
        mine = sorted((s for s in stories if s["section"] == section), key=lambda s: -s["score"])[:8]
        for n, s in enumerate(mine, 1):
            s["id"] = f"{LETTER[section]}{n}"
            result["stories"].append(s)
    save(os.path.join(DESK, "research", "latest.json"), result)
    save(os.path.join(DESK, "research", now().strftime("%Y%m%d-%H%M") + ".json"), result)
    return {"ok": True, "feeds_read": result["feeds_read"], "feeds_failed": failed, "stories": len(result["stories"]), "digest": digest(result)}


def digest(result):
    """The research as the Researcher reads it: short enough for a small model's context."""
    lines = [f"RESEARCH {result['made'][:16].replace('T', ' ')} UTC — {result['feeds_read']} feeds read" +
             (f", {len(result['feeds_failed'])} failed" if result["feeds_failed"] else "")]
    for section in LETTER:
        lines += ["", section.upper()]
        mine = [s for s in result["stories"] if s["section"] == section]
        if not mine:
            lines.append("  (nothing new)")
        for s in mine:
            who = ", ".join(s["outlets"][:3])
            lines.append(f"[{s['id']}] {s['title']} ({who} · {len(s['outlets'])} outlet{'s' if len(s['outlets']) != 1 else ''} · {s['age_hours']:.0f}h ago)")
            if s["summary"]:
                lines.append("     " + clean(s["summary"], 200))
    return "\n".join(lines)


def find_story(story_id):
    latest = read(os.path.join(DESK, "research", "latest.json"), {"stories": []})
    return next((s for s in latest["stories"] if s["id"].lower() == str(story_id).strip().strip("[]").lower()), None), latest


def article_text(url, limit=2200):
    """The article's own paragraphs, as plain text, for the Researcher to take facts from.
    Kept on this machine only (desk/); never published. Empty when the page will not give them."""
    try:
        raw = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": AGENT}), timeout=20).read(900_000)
        page = raw.decode("utf-8", "replace")
    except Exception:
        return ""
    page = re.sub(r"(?is)<(script|style|noscript|figure|aside|nav|header|footer|form)\b.*?</\1>", " ", page)
    paragraphs = [clean(p) for p in re.findall(r"(?is)<p\b[^>]*>(.*?)</p>", page)]
    paragraphs = [p for p in paragraphs if len(p) >= 70 and not re.search(
        r"(?i)cookie|subscribe|newsletter|sign up|all rights reserved|advertis|disrupt|exhibit|book .{0,30}now|get your pass|register (now|today)|save up to", p)]
    text = ""
    for p in paragraphs:
        if len(text) + len(p) > limit:
            break
        text += p + "\n"
    return text.strip()


def corpus(s):
    """Everything the sources say about a story, as one text."""
    return " ".join(" ".join([x.get("title", ""), x.get("summary", ""), x.get("text", "")]) for x in s["sources"])


def story(story_id):
    """One story's sources, with the first two articles' text fetched (once) for the facts."""
    s, latest = find_story(story_id)
    if not s:
        return {"ok": False, "error": f"There is no story {story_id} in the latest research. Run research and use an id from its list, like A2."}
    changed = False
    for source in s["sources"][:2]:
        if "text" not in source:
            source["text"] = article_text(source["url"])
            changed = True
    if changed:
        save(os.path.join(DESK, "research", "latest.json"), latest)
    enough = len(corpus(s)) >= 700
    return {"ok": True, "id": s["id"], "section": s["section"], "title": s["title"], "sources": s["sources"],
            "note": "Take every fact from the text above." if enough else
                    "THIN: the sources say too little for a story. Choose a different story in this section, or skip the section."}


# ── the checks ────────────────────────────────────────────────────────────────

def ungrounded(text, source_text):
    """Names and numbers in `text` that the sources never mention. A writer uses their own
    words, but a name or a figure has to come from somewhere: these did not."""
    have = norm(source_text)
    have_words = set(re.findall(r"[a-z0-9][a-z0-9'.-]*", have))
    missing = []
    for number in re.findall(r"\d[\d,.]*\d|\d", text):
        if number.replace(",", "").rstrip(".") not in have.replace(",", "") and number not in have:
            missing.append(number)
    for sentence in re.split(r"(?<=[.!?:])\s+|\n+", text):       # a capitalised word that does not start a sentence is a name
        for word in re.findall(r"[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'’-]*", sentence)[1:]:
            if not word[0].isupper():
                continue
            low = norm(word).strip("'")
            low = low[:-2] if low.endswith("'s") else low
            if low in COMMON or len(low) < 3 or low in have_words or low in have:
                continue
            missing.append(word)
    seen, out = set(), []
    for m in missing:
        if m.lower() not in seen:
            seen.add(m.lower()); out.append(m)
    return out


def copied(text, source_text):
    """Passages of eight or more words taken word for word from the sources (quotations aside)."""
    outside_quotes = re.sub(r"[\"“][^\"”]{0,300}[\"”]", " ", text)
    tokens = re.findall(r"[a-z0-9']+", norm(outside_quotes))
    theirs_tokens = re.findall(r"[a-z0-9']+", norm(source_text))
    theirs = {" ".join(theirs_tokens[i:i + 8]) for i in range(len(theirs_tokens) - 7)}
    runs, i = [], 0
    while i <= len(tokens) - 8:
        if " ".join(tokens[i:i + 8]) in theirs:
            j = i + 8
            while j < len(tokens) and " ".join(tokens[j - 7:j + 1]) in theirs:
                j += 1
            runs.append(" ".join(tokens[i:j]))
            i = j
        else:
            i += 1
    return runs


def unsupported(sentences, source_text):
    """Sentences most of whose telling words the brief and its sources never use: padding or invention."""
    have = words(source_text)
    stems = {w[:5] for w in have}
    out = []
    for sentence in sentences:
        telling = list(words(sentence))
        if len(telling) < 5:
            continue
        if sum(1 for w in telling if w in have or w[:5] in stems) < 0.5 * len(telling):
            out.append(sentence.strip())
    return out


# ── briefs ────────────────────────────────────────────────────────────────────

def brief(story_id, angle, points, by="Researcher", section=""):
    s, latest = find_story(story_id)
    if not s:
        return {"ok": False, "error": f"There is no story {story_id} in the latest research. Use an id from its list, like A2."}
    section = clean(section).lower().replace("u.s.", "us")
    if section in LETTER:                              # the Researcher may move a story the feeds filed in the wrong section
        s = dict(s, section=section)
    if "text" not in s["sources"][0]:
        return {"ok": False, "error": f"Read the story first: call NewsStory for {s['id']}, then file the brief from what its sources say."}
    everything = corpus(s)
    if len(everything) < 700:
        return {"ok": False, "error": f"Story {s['id']} is too thin: its sources say too little to write from. Choose a different story in this section, or skip the section. Do not pad a brief with guesses."}
    points = [clean(p) for p in (points or []) if clean(p)]
    angle = clean(angle)
    problems = []
    if not 3 <= len(points) <= 7:
        problems.append(f"Give 3 to 7 facts; you gave {len(points)}. Every fact must be in the sources' text.")
    problems += [f"Fact {n} is too long ({len(p)} characters); keep each under 320." for n, p in enumerate(points, 1) if len(p) > 320]
    problems += [f"Fact {n} is too short to be a fact: \"{p}\"." for n, p in enumerate(points, 1) if len(p) < 20]
    outlets = " ".join(x["outlet"] for x in s["sources"])
    have = words(everything)
    for n, point in enumerate(points, 1):
        strangers = ungrounded(point, everything + " " + outlets)
        if strangers:
            problems.append(f"Fact {n} has names or numbers that are not in the sources: {', '.join(strangers[:6])}. Use only what the sources say.")
        telling = list(words(point))
        if telling and sum(1 for w in telling if w in have) < 0.55 * len(telling):
            problems.append(f"Fact {n} is not what the sources say (most of its words are not in them). Take it from the text, or drop it.")
    if not 20 <= len(angle) <= 260:
        problems.append("The angle is one sentence saying why this story matters today (20 to 260 characters).")
    if any(b.get("story_urls") == sorted(x["url"] for x in s["sources"]) for b in briefs()):
        problems.append(f"Story {s['id']} already has a brief. Pick another story.")
    if len([b for b in briefs("ready") if b["section"] == s["section"]]) >= 3:
        problems.append(f"There are already 3 {s['section']} briefs waiting to be written. Pick a story from another section.")
    if problems:
        return {"ok": False, "problems": problems}
    key = hashlib.sha1("|".join(sorted(x["url"] for x in s["sources"])).encode()).hexdigest()[:6]
    bid = f"{now().strftime('%Y%m%d')}-{s['section']}-{key}"
    save(os.path.join(DESK, "briefs", bid + ".json"), {
        "id": bid, "status": "ready", "section": s["section"], "working_title": s["title"], "angle": angle, "points": points,
        "sources": [{"outlet": x["outlet"], "title": x["title"], "url": x["url"]} for x in s["sources"]],
        "source_text": everything[:9000],              # what the story will be checked against when it is written
        "story_urls": sorted(x["url"] for x in s["sources"]), "researched_by": by, "created": now().isoformat()})
    return {"ok": True, "brief": bid, "section": s["section"], "waiting": len(briefs("ready"))}


def queue():
    """The next brief to write, alone: one story at a time keeps a small model from mixing two up."""
    ready = briefs("ready")
    if not ready:
        return {"ok": True, "waiting": 0, "note": "No briefs are waiting. There is nothing to write."}
    b = ready[0]
    return {"ok": True, "waiting": len(ready), "brief": b["id"], "section": b["section"], "what_it_is_about": b["working_title"],
            "angle": b["angle"], "facts": b["points"], "outlets": sorted({x["outlet"] for x in b["sources"]}),
            "note": "Write this one story in your own words from these facts, publish it with NewsPublish, then call NewsQueue again for the next."}


# ── publishing ────────────────────────────────────────────────────────────────

def parse_story(content):
    """Body paragraphs, then '## Key points' as a list, then '## Why it matters'."""
    text = re.sub(r"\r\n?", "\n", content or "").strip()
    parts = re.split(r"(?im)^\s*#{1,3}\s*(key points|why it matters)\s*:?\s*$", text)
    plain = lambda t: re.sub(r"[*_`]+", "", t).strip()
    body = [clean(plain(p)) for p in re.split(r"\n\s*\n", parts[0]) if clean(plain(p))]
    body = [p for p in body if not p.startswith("#")]
    points, why = [], ""
    for name, chunk in zip(parts[1::2], parts[2::2]):
        if name.lower().startswith("key"):
            points = [clean(plain(re.sub(r"^\s*([-*•]|\d+[.)])\s*", "", line))) for line in chunk.strip().splitlines() if clean(line)]
        else:
            why = clean(plain(chunk))
    return body, points, why


def slugify(title):
    return re.sub(r"[^a-z0-9]+", "-", norm(title)).strip("-")[:70].rstrip("-")


def eastern_day(moment):
    return moment.astimezone(site_build.EASTERN).date()


def publish(brief_id, title, summary, content, by="Poster", push=True):
    path = os.path.join(DESK, "briefs", str(brief_id).strip() + ".json")
    b = read(path)
    if not b:
        return {"ok": False, "error": f"There is no brief {brief_id}. Call NewsQueue for the brief to write."}
    if b.get("status") != "ready":
        return {"ok": False, "error": f"Brief {brief_id} is finished with. Call NewsQueue for the next one."}
    title = clean(title).strip("\"“”'").rstrip(".")
    summary = clean(summary)
    body, points, why = parse_story(content)
    count = sum(len(p.split()) for p in body)
    problems = []
    if not 25 <= len(title) <= 110:
        problems.append(f"The headline is {len(title)} characters; it must be 25 to 110.")
    if title.isupper():
        problems.append("The headline is all capitals. Write it as a sentence.")
    if not 60 <= len(summary) <= 260:
        problems.append(f"The summary is {len(summary)} characters; it must be 60 to 260: one or two sentences.")
    if len(body) < 3:
        problems.append(f"The story has {len(body)} paragraph(s); it needs at least 3, separated by blank lines.")
    if count > 650:
        problems.append(f"The story is {count} words; keep it under 650.")
    if count < 80:
        problems.append(f"The story is {count} words; it needs at least 80. Use more of the brief's facts. Do not add anything that is not in them.")
    if not 2 <= len(points) <= 5:
        problems.append("After the story add a line '## Key points' and 2 to 5 lines that each start with '- '.")
    if not 12 <= len(why.split()) <= 120:
        problems.append("After the key points add a line '## Why it matters' and one paragraph of 12 to 120 words.")
    everything = " \n".join([title, summary] + body + points + [why])
    if re.search(r"https?://", everything):
        problems.append("Leave web addresses out of the text: the sources are listed under the story automatically.")
    if re.search(r"\b(as an ai|i cannot|language model)\b", everything, re.I):
        problems.append("The text talks about being an AI. Write only the news.")

    known = " ".join([b.get("source_text", ""), b["working_title"], b["angle"]] + b["points"] + [x["outlet"] + " " + x["title"] for x in b["sources"]])
    about = words(" ".join(b["points"]))
    if about and len(about & words(everything)) < 0.35 * len(about):
        problems.append(f"This is not the story in brief {b['id']}: it hardly mentions that brief's facts. Call NewsQueue, read the facts again, and write that story.")
    else:
        strangers = ungrounded(everything, known)
        if strangers:
            problems.append("These names or numbers are not in the brief or its sources: " + ", ".join(strangers[:10]) +
                            ". Check each against the brief's facts and correct it. Do not simply delete a number: the sentence must still say something exact.")
        lifted = copied(" \n".join(body + points + [why, summary]), b.get("source_text", ""))
        if lifted:
            problems.append("These passages are copied word for word from the sources. Say each in your own words (a short quotation in quotation marks is fine): " +
                            " | ".join('"' + r[:110] + '"' for r in lifted[:4]))
        sentences = [x for para in body + [why] for x in re.split(r"(?<=[.!?])\s+", para)]
        loose = unsupported(sentences, known)
        if loose:
            problems.append("These sentences say things the brief and its sources do not: " + " | ".join('"' + x[:120] + '"' for x in loose[:3]) +
                            ". Remove them. A short story of true facts is better than a longer one with guesses.")
    if any(alike(title, x["title"]) >= 0.8 for x in b["sources"]) or alike(title, b["working_title"]) >= 0.8:
        problems.append("The headline repeats a source's headline. Write your own: say what happened in a plain sentence.")
    if re.search(r"\((?:%s)\)" % "|".join(re.escape(x["outlet"]) for x in b["sources"]), everything):
        problems.append("Do not put the outlet in brackets after a sentence. Name it in the sentence: \"according to BBC News\" or \"BBC News reports\".")
    if alike(why, b["angle"]) >= 0.85 and len(why.split()) < 30:
        problems.append("'Why it matters' only repeats the angle. Write two or three sentences on what this changes and for whom, from the brief's facts.")
    if len({norm(x) for x in points} & {norm(x) for para in body for x in re.split(r"(?<=[.!?])\s+", para)}) >= 2:
        problems.append("The key points repeat sentences from the story word for word. Make each key point a short fact of its own (under 25 words).")

    posts = published_posts()
    if any(alike(title, p["title"]) >= 0.72 for p in posts[-80:]):
        problems.append("A story with almost this headline has already been published.")
    today = [p for p in posts if eastern_day(dt.datetime.fromisoformat(p["published"].replace("Z", "+00:00"))) == eastern_day(now())]
    limit = len(today) >= 14 or len([p for p in today if p["section"] == b["section"]]) >= 4
    if limit:
        problems.append("The day's limit has been reached (14 stories, 4 in a section). Stop publishing for today.")
    if not b.get("sources"):
        problems.append("This brief has no sources, so its story cannot run.")
    if problems:
        b["attempts"] = b.get("attempts", 0) + 1
        if b["attempts"] >= 4 and not limit:             # a story that cannot be got right is set aside, so the rest can run
            b["status"], b["skipped_because"] = "skipped", problems
            save(path, b)
            return {"ok": False, "set_aside": True, "problems": problems,
                    "fix": "This story has been refused four times and is set aside. Call NewsQueue and go on to the next."}
        save(path, b)
        return {"ok": False, "problems": problems, "fix": "Correct these and publish the same brief again."}

    stamp = now().replace(microsecond=0)
    slug = f"{eastern_day(stamp).isoformat()}-{slugify(title)}"
    post = {"slug": slug, "title": title, "summary": summary, "section": b["section"], "body": body, "key_points": points,
            "why_it_matters": why, "sources": b["sources"], "published": stamp.isoformat().replace("+00:00", "Z"),
            "written_by": by, "researched_by": b.get("researched_by", "Researcher"), "brief": b["id"]}
    save(os.path.join(POSTS, slug + ".json"), post)
    b["status"], b["published_as"] = "published", slug
    save(path, b)
    total = site_build.build()
    site = site_build.load_site()
    pushed = commit(f"Publish: {title}", push)
    return {"ok": True, "url": f"{site['base_url'].rstrip('/')}/posts/{slug}.html", "section": b["section"], "words": count,
            "stories_on_site": total, "pushed": pushed, "waiting": len(briefs("ready"))}


def unpublish(slug, push=True):
    path = os.path.join(POSTS, slug + ".json")
    if not os.path.exists(path):
        return {"ok": False, "error": f"There is no story {slug}."}
    title = (read(path) or {}).get("title", slug)
    os.remove(path)
    site_build.build()
    return {"ok": True, "removed": slug, "pushed": commit(f"Remove: {title}", push)}


def commit(message, push=True):
    """Commit whatever changed and send it to GitHub. Returns what happened, in a word or two."""
    def git(*args, timeout=90):
        return subprocess.run(["git", "-C", ROOT] + list(args), capture_output=True, text=True, timeout=timeout)
    if git("rev-parse", "--git-dir").returncode != 0:
        return "not a git repository"
    git("add", "-A")
    if git("diff", "--cached", "--quiet").returncode == 0:
        return "nothing changed"
    done = git("commit", "-q", "-m", message)
    if done.returncode != 0:
        return "commit failed: " + (done.stderr or done.stdout).strip()[:160]
    if not push or os.environ.get("NEWSDESK_NO_PUSH") == "1":
        return "committed, not pushed"
    if not git("remote").stdout.strip():
        return "committed; no remote to push to"
    sent = git("push", "-q", "origin", "HEAD", timeout=120)
    return "pushed" if sent.returncode == 0 else "committed; push failed: " + (sent.stderr or sent.stdout).strip()[:160]


def status():
    posts = published_posts()
    today = [p for p in posts if eastern_day(dt.datetime.fromisoformat(p["published"].replace("Z", "+00:00"))) == eastern_day(now())]
    latest = read(os.path.join(DESK, "research", "latest.json"), {})
    site = site_build.load_site()
    aside = [b for b in briefs("skipped") if b.get("created", "")[:10] == now().isoformat()[:10]]
    return {"ok": True, "site": site["base_url"], "stories_on_site": len(posts), "published_today": len(today),
            "today_by_section": {s: len([p for p in today if p["section"] == s]) for s in LETTER},
            "today": [{"title": p["title"], "section": p["section"], "url": f"{site['base_url'].rstrip('/')}/posts/{p['slug']}.html"} for p in today],
            "briefs_waiting": len(briefs("ready")),
            "set_aside_today": [{"about": b["working_title"], "why": b.get("skipped_because", [])[:2]} for b in aside],
            "last_research": (latest.get("made") or "never")[:16]}


def main():
    import argparse
    ap = argparse.ArgumentParser(description="The news desk")
    ap.add_argument("action", choices=["research", "story", "brief", "queue", "publish", "status", "unpublish", "build"])
    ap.add_argument("--json", default="{}")
    ap.add_argument("--content-file")
    a = ap.parse_args()
    args = json.loads(a.json)
    if a.action == "research":
        out = research()
        print(out.pop("digest"))
    elif a.action == "story":
        out = story(args.get("story", ""))
    elif a.action == "brief":
        out = brief(args.get("story", ""), args.get("angle", ""), args.get("points", []), args.get("by", "Researcher"), args.get("section", ""))
    elif a.action == "queue":
        out = queue()
    elif a.action == "publish":
        content = open(a.content_file, encoding="utf-8").read() if a.content_file else args.get("content", "")
        out = publish(args.get("brief", ""), args.get("title", ""), args.get("summary", ""), content, args.get("by", "Poster"))
    elif a.action == "unpublish":
        out = unpublish(args.get("slug", ""))
    elif a.action == "build":
        out = {"ok": True, "stories": site_build.build()}
    else:
        out = status()
    print(json.dumps(out, indent=1, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
