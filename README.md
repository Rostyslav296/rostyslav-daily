# Rostyslav Daily

A daily briefing on world and U.S. news, technology, artificial intelligence and robotics,
hosted on GitHub Pages. The stories are researched and written by two AI agents,
**Researcher** and **Poster**, from the public news feeds of established outlets. Every
story links to its sources.

**Live URL:** https://rostyslav296.github.io/rostyslav-daily/

Published by Rostyslav Cloud LLC.

## Website architecture

```
rostyslav-daily/
├── site.json             The site's name, tagline, sections and social links
├── content/posts/        One JSON file per story: the only place the words live
├── css/styles.css        All styles (colours, type, layout, dark mode, phone layout)
├── js/main.js            Today's date in the masthead, "3 hours ago" beside recent stories
├── tools/
│   ├── build.py          Makes every page from content/posts and site.json
│   ├── newsdesk.py       The news desk: research, briefs, publishing (what the agents use)
│   └── feeds.json        The outlets the Researcher reads, by section
├── index.html            Home: the latest edition                        ┐
├── world.html us.html tech.html ai.html robotics.html   Section pages    │ all written by
├── archive.html          Every story                                     │ tools/build.py;
├── social.html           Social links                                    │ never edited
├── about.html            What this is, standards, corrections            │ by hand
├── posts/                One page per story                              │
└── feed.xml sitemap.xml robots.txt 404.html                              ┘
```

No build service and no dependencies: Python's standard library, plain HTML and CSS.

## How a story gets here

1. **Researcher** runs `newsdesk.py research`. It reads the feeds in `tools/feeds.json`,
   keeps what is recent, groups the same story across outlets, and ranks stories by how
   many outlets carry them. Researcher then files a **brief** for each story it picks:
   the facts, the angle, and the links.
2. **Poster** takes each brief from the queue, writes the story in its own words, and
   runs `newsdesk.py publish`. That checks the story (length, a headline and summary of
   sensible size, key points, "why it matters", at least one source, not a repeat, the
   day's limits), writes its file into `content/posts/`, rebuilds the site, commits and
   pushes. A story that fails a check is refused with the reason, and Poster fixes it.

The agents live in the Rostyslav app and work twice a day while it is open and the
project is switched on. The desk's working files (`desk/`) stay on the machine that runs
it; only published stories are in this repository.

## How to change things by hand

```bash
python3 tools/build.py            # rebuild every page after any change below
git add -A && git commit -m "..." && git push
```

- **Rename the site, change the tagline or a section's blurb:** edit `site.json`.
- **Add a social account:** in `site.json`, put the address in that account's `"url"`.
  An empty `"url"` shows the card as "Coming soon".
- **Add or drop an outlet:** edit `tools/feeds.json`.
- **Correct a story:** edit its file in `content/posts/`.
- **Remove a story:** `python3 tools/newsdesk.py unpublish --json '{"slug": "..."}'`
  (the slug is the file name without `.json`). This rebuilds, commits and pushes.
- **Change the look:** `css/styles.css`. The colours are the variables at the top.

## Standards

Summaries in the site's own words, with the facts attributed to the outlet that reported
them. No invented quotations, names or numbers. News, not opinion. Every story says it
was written by an AI agent and has not been checked by a person. Corrections: open an
issue on this repository.
