#!/usr/bin/env python3
"""Render profile/panel.svg — character art beside live account numbers.

Runs inside the profile workflow. No third-party packages: the art is read from
a committed text file and the numbers come from GitHub's GraphQL API, so all it
needs is a token that can see your private repositories.

    GITHUB_TOKEN=<pat> USERNAME=CreatorBjorn python3 scripts/build_panel.py

To show a different picture, replace profile/portrait.txt. To change what the
panel says about you, edit PROFILE below.
"""
import datetime as dt
import html
import json
import os
import sys
import urllib.error
import urllib.request

# ---------------------------------------------------------------- settings --
DISPLAY_NAME = "Creator Bjorn"
PROFILE = [                       # label, value — the fixed half of the panel
    ("role", "Game developer · Web engineer"),
    ("stack", "Unity 6 · Next.js · TypeScript"),
    ("focus", "gameplay systems · local search"),
]
FIRE = True                       # vertical ember gradient on the art

PORTRAIT = "profile/portrait.txt"
OUT = "profile/panel.svg"
API = "https://api.github.com/graphql"

RAMP = " .:-=+*#%@"                                   # empty -> brightest
TIERS = ["#5c3a2a", "#a8552b", "#e0813c", "#ffcf9e"]  # colour per density tier

# ------------------------------------------------------------------ layout --
CW, LH, FS = 7.22, 11.6, 12       # default character cell and font size
PORTRAIT_MAX_H = 640              # tallest the art may get, px
CELL_ASPECT = 0.5                 # width/height of the cell the art was drawn for
LEFT_X = 40
TOP = 56
ROW_H = 26
ROW_W = 560
ADV = 8.43                        # monospace advance at font-size 14
NBSP = " "                   # plain spaces collapse inside SVG text

QUERY = """
query($login: String!) {
  user(login: $login) {
    login
    createdAt
    repositories(first: 100, isFork: false,
                 affiliations: [OWNER, ORGANIZATION_MEMBER, COLLABORATOR],
                 ownerAffiliations: [OWNER, ORGANIZATION_MEMBER, COLLABORATOR]) {
      totalCount
      nodes { nameWithOwner isPrivate primaryLanguage { name } }
    }
    contributionsCollection {
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isPrivate primaryLanguage { name } }
        contributions { totalCount }
      }
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""

# contributionsCollection only covers one year per call, so the all-time
# project list is collected year by year, from the account's first year to today
YEAR_QUERY = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      commitContributionsByRepository(maxRepositories: 100) {
        repository { nameWithOwner isPrivate primaryLanguage { name } }
        contributions { totalCount }
      }
    }
  }
}
"""

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


# -------------------------------------------------------------------- data --
# GitHub guesses a repo's language from file extensions and gets Unity/web
# projects wrong (shader, .m and markup files). These never show up in the panel.
IGNORE_LANGS = {
    "Wolfram Language", "Mathematica", "Objective-C", "ShaderLab", "HLSL", "GLSL",
    "HTML", "CSS", "SCSS", "Python", "Shell", "PowerShell", "Batchfile",
    "Dockerfile", "Makefile", "Jupyter Notebook",
}
FALLBACK_LANGS = ["C#", "TypeScript"]   # shown if nothing else is left


def graphql(token, query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    req = urllib.request.Request(API, data=body, headers={
        "Authorization": "bearer " + token,
        "Content-Type": "application/json",
        "User-Agent": "profile-panel",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        payload = json.load(r)
    if "errors" in payload:
        raise RuntimeError(payload["errors"][0].get("message", "GraphQL error"))
    return payload["data"]["user"]


def fetch(token, login):
    user = graphql(token, QUERY, {"login": login})
    # every repo you ever committed to, merged across years
    merged = {}
    now = dt.datetime.now(dt.timezone.utc)
    year = int(user["createdAt"][:4])
    try:
        while year <= now.year:
            # GitHub allows at most one year per call; Dec 31 23:59:59 keeps leap years inside it
            start = dt.datetime(year, 1, 1, tzinfo=dt.timezone.utc)
            end = min(dt.datetime(year, 12, 31, 23, 59, 59, tzinfo=dt.timezone.utc), now)
            part = graphql(token, YEAR_QUERY, {
                "login": login,
                "from": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            })
            for item in part["contributionsCollection"]["commitContributionsByRepository"] or []:
                key = item["repository"]["nameWithOwner"].lower()
                if key in merged:
                    merged[key]["contributions"]["totalCount"] += item["contributions"]["totalCount"]
                else:
                    merged[key] = item
            year += 1
        user["allTimeRepos"] = list(merged.values())
    except (urllib.error.URLError, RuntimeError, KeyError, TypeError) as e:
        # the rest of the panel still gets rebuilt; projects fall back to the last 12 months
        print("all-time project list failed (%s) — using the last 12 months" % e, file=sys.stderr)
    return user


def stats(user, today=None):
    today = today or dt.date.today()
    c = user["contributionsCollection"]
    cal = c["contributionCalendar"]
    days = sorted(
        (dt.date.fromisoformat(d["date"]), d["contributionCount"])
        for w in cal["weeks"] for d in w["contributionDays"]
    )
    days = [(d, n) for d, n in days if d <= today]

    # current streak — today may not be over yet, so an empty today doesn't break it
    streak, i = 0, len(days) - 1
    if i >= 0 and days[i][1] == 0 and days[i][0] == today:
        i -= 1
    while i >= 0 and days[i][1] > 0:
        streak, i = streak + 1, i - 1

    longest = run = 0
    for _, n in days:
        run = run + 1 if n > 0 else 0
        longest = max(longest, run)

    by_wd = [0] * 7
    for d, n in days:
        by_wd[d.weekday()] += n
    busiest = WEEKDAYS[by_wd.index(max(by_wd))] if any(by_wd) else "—"

    # last 12 calendar months, oldest first
    months = []
    y, m = today.year, today.month
    for _ in range(12):
        months.append((y, m))
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    months.reverse()
    per = {k: 0 for k in months}
    for d, n in days:
        if (d.year, d.month) in per:
            per[(d.year, d.month)] += n

    # what you actually worked on: every repo you ever committed to,
    # org repos included, weighted by your own commits; the profile repo is left out
    profile_repo = ("%s/%s" % (user["login"], user["login"])).lower()
    worked, langs = [], {}
    for item in user.get("allTimeRepos") or c.get("commitContributionsByRepository") or []:
        repo = item["repository"]
        if repo["nameWithOwner"].lower() == profile_repo:
            continue
        worked.append(repo)
        n = item["contributions"]["totalCount"]
        if repo.get("primaryLanguage"):
            name = repo["primaryLanguage"]["name"]
            langs[name] = langs.get(name, 0) + n
    # GitHub hides commits it can't tie to your account (other e-mail, side
    # branches). If none were found, count the repos you are part of instead:
    # your own plus the organisations you belong to.
    if not worked:
        for repo in (user.get("repositories") or {}).get("nodes") or []:
            if repo["nameWithOwner"].lower() == profile_repo:
                continue
            worked.append(repo)
            if repo.get("primaryLanguage"):
                name = repo["primaryLanguage"]["name"]
                langs[name] = langs.get(name, 0) + 1
    print("projects: %d commit-linked, %d you belong to -> showing %d" % (
        len(user.get("allTimeRepos") or c.get("commitContributionsByRepository") or []),
        len((user.get("repositories") or {}).get("nodes") or []), len(worked)))
    top = [n for n, _ in sorted(langs.items(), key=lambda kv: -kv[1])
           if n not in IGNORE_LANGS][:3] or FALLBACK_LANGS

    return {
        "contributions": cal["totalContributions"],
        "commits": c["totalCommitContributions"] + c.get("restrictedContributionsCount", 0),
        "prs": c["totalPullRequestContributions"],
        "repos": len(worked),
        "private": sum(1 for r in worked if r["isPrivate"]),
        "all_time": "allTimeRepos" in user,
        "langs": " · ".join(top) or "—",
        "streak": streak,
        "longest": longest,
        "busiest": busiest,
        "since": user["createdAt"][:4],
        "months": [(dt.date(y, m, 1).strftime("%b")[0], per[(y, m)]) for y, m in months],
    }


# ------------------------------------------------------------------ render --
def esc(text):
    return html.escape(str(text)).replace(" ", NBSP)


def portrait_lines():
    if not os.path.exists(PORTRAIT):
        return []
    with open(PORTRAIT, encoding="utf-8") as f:
        return [ln.rstrip("\n") for ln in f]


def tier_of(ch):
    if "⠀" <= ch <= "⣿":                    # braille: by lit dots
        return min(3, bin(ord(ch) - 0x2800).count("1") * 4 // 9)
    i = RAMP.find(ch)
    return 3 if i < 0 else min(3, int(i / len(RAMP) * 4))


def portrait_svg(lines, x, y0, cw, lh):
    cols = max(len(ln) for ln in lines)
    lines = [ln.ljust(cols) for ln in lines]          # equal widths, or textLength skews rows
    fills = list(TIERS)
    if FIRE:                                          # bright tiers pick up the ember gradient
        fills[3], fills[2] = "url(#pnFire)", "url(#pnFireDim)"
    out = []
    for r, ln in enumerate(lines):
        if not ln.strip():
            continue
        spans, cur, buf = [], None, []
        for ch in ln:
            t = tier_of(ch)
            if t != cur and buf:
                spans.append((cur, "".join(buf)))
                buf = []
            cur = t
            buf.append(ch)
        if buf:
            spans.append((cur, "".join(buf)))
        body = "".join('<tspan fill="%s">%s</tspan>' % (fills[t], esc(s)) for t, s in spans)
        out.append('<text x="%s" y="%.1f" textLength="%.1f" lengthAdjust="spacingAndGlyphs">%s</text>'
                   % (x, y0 + (r + 0.82) * lh, cols * cw, body))
    return "\n    ".join(out), len(lines) * lh


def row(x, y, label, value, accent="#a3b4c4"):
    value = str(value)
    label_end = len(label) * ADV
    gap = (ROW_W - len(value) * ADV) - label_end - 2 * ADV
    dots = "." * max(0, int(gap / ADV))
    return ('<text x="%s" y="%s" font-size="14" fill="#6f7f8f">%s</text>'
            '<text x="%.1f" y="%s" font-size="14" fill="#4b5763">%s</text>'
            '<text x="%s" y="%s" font-size="14" fill="%s" text-anchor="end">%s</text>'
            % (x, y, esc(label), x + label_end + ADV, y, dots, x + ROW_W, y, accent, esc(value)))


def section(x, y, title):
    w = len(title) * 8 + 16
    return ('<text x="%s" y="%s" font-size="12" fill="#e0813c" letter-spacing="3">%s</text>'
            '<rect x="%s" y="%s" width="%s" height="1" fill="#e0813c" opacity=".3"/>'
            % (x, y, esc(title), x + w, y - 4, ROW_W - w))


def sparkline(x, y, months):
    """12 monthly bars, the latest one highlighted."""
    h, gap = 38, 8
    bw = (ROW_W - gap * 11) / 12.0
    peak = max((n for _, n in months), default=0) or 1
    out = ['<text x="%s" y="%s" font-size="11" fill="#6f7f8f" letter-spacing="1.5">last 12 months</text>' % (x, y)]
    y += 10
    for i, (label, n) in enumerate(months):
        bx = x + i * (bw + gap)
        bh = max(2, round(h * n / peak, 1))
        last = i == len(months) - 1
        out.append('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="%s" opacity="%s"/>'
                   % (bx, y + h - bh, bw, bh, "#ffcf9e" if last else "#e0813c", "1" if last else ".75"))
        out.append('<text x="%.1f" y="%.1f" font-size="10" fill="#4b5763" text-anchor="middle">%s</text>'
                   % (bx + bw / 2, y + h + 14, esc(label)))
    return out, y + h + 14


def text_column(x, y0, s):
    out, y = [], y0
    out.append('<text x="%s" y="%s" font-size="17" fill="#f2f5f8" font-weight="bold" letter-spacing="1">%s</text>'
               % (x, y, esc(DISPLAY_NAME)))
    out.append('<circle cx="%s" cy="%s" r="4" fill="#57e08a"><animate attributeName="opacity" '
               'values="1;.25;1" dur="2.4s" repeatCount="indefinite"/></circle>' % (x + ROW_W, y - 6))
    y += 36
    out.append(section(x, y, "PROFILE")); y += ROW_H
    for label, value in PROFILE + [("on github", "since %s" % s["since"])]:
        out.append(row(x, y, label, value)); y += ROW_H
    y += 12
    out.append(section(x, y, "SIGNAL")); y += ROW_H
    streak = "%s day%s" % (s["streak"], "" if s["streak"] == 1 else "s")
    longest = "%s day%s" % (s["longest"], "" if s["longest"] == 1 else "s")
    signal = [
        ("contributions", "%s  (last 12 months)" % s["contributions"], "#ffcf9e"),
        ("commits", s["commits"], "#e0813c"),
    ]
    if s["prs"]:
        signal.append(("pull requests", s["prs"], "#a3b4c4"))
    if s["repos"]:
        signal.append(("projects", "%s  (%s, %s private)" % (s["repos"], "all time" if s["all_time"] else "last 12 months", s["private"]), "#a3b4c4"))
    for label, value, col in signal + [
        ("languages", s["langs"], "#a3b4c4"),
        ("current streak", streak, "#ffcf9e" if s["streak"] else "#a3b4c4"),
        ("longest streak", longest, "#a3b4c4"),
        ("busiest day", s["busiest"], "#a3b4c4"),
    ]:
        out.append(row(x, y, label, value, col)); y += ROW_H
    y += 16
    bars, y = sparkline(x, y, s["months"])
    return out + bars, y


def build(s, lines):
    if lines:
        lh = min(LH, PORTRAIT_MAX_H / len(lines))
        cw, fs = lh * CELL_ASPECT, lh * (FS / LH)
        cols = max(len(ln) for ln in lines)
        art, art_h = portrait_svg(lines, LEFT_X, TOP, cw, lh)
        right_x = int(LEFT_X + cols * cw + 64)
    else:
        art, art_h, fs, right_x = "", 0, FS, LEFT_X
    width = right_x + ROW_W + 48

    _, measured = text_column(right_x, 0, s)            # measure, then centre on the art
    text_h = measured + 20
    y0 = TOP + max(0, int((art_h - text_h) / 2)) + 20
    column, text_end = text_column(right_x, y0, s)

    height = int(max(TOP + art_h, text_end) + 78)
    fade = round(1 - 34.0 / height, 4)
    today = dt.date.today().isoformat()
    alt = "%s — %s contributions in the last 12 months" % (DISPLAY_NAME, s["contributions"])

    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 %(w)s %(h)s" width="%(w)s" height="%(h)s" role="img" aria-label="%(alt)s">
  <defs>
    <linearGradient id="pnGround" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#10151b"/><stop offset=".6" stop-color="#151319"/><stop offset="1" stop-color="#1c1012"/></linearGradient>
    <radialGradient id="pnGlow" cx=".14" cy="1.05" r=".7"><stop offset="0" stop-color="#f08b3e" stop-opacity=".28"/><stop offset="1" stop-color="#c04d1e" stop-opacity="0"/></radialGradient>
    <linearGradient id="pnFire" gradientUnits="userSpaceOnUse" x1="0" y1="%(top)s" x2="0" y2="%(artb)s"><stop offset="0" stop-color="#fff1d6"/><stop offset=".45" stop-color="#ffc27a"/><stop offset="1" stop-color="#e2602a"/></linearGradient>
    <linearGradient id="pnFireDim" gradientUnits="userSpaceOnUse" x1="0" y1="%(top)s" x2="0" y2="%(artb)s"><stop offset="0" stop-color="#d9a877"/><stop offset="1" stop-color="#a8431c"/></linearGradient>
    <linearGradient id="pnFade" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff"/><stop offset="%(fade)s" stop-color="#fff"/><stop offset="1" stop-color="#000"/></linearGradient>
    <mask id="pnMask"><rect width="%(w)s" height="%(h)s" fill="url(#pnFade)"/></mask>
  </defs>
  <g mask="url(#pnMask)">
    <rect width="%(w)s" height="%(h)s" fill="url(#pnGround)"/>
    <rect width="%(w)s" height="%(h)s" fill="url(#pnGlow)"/>
    <g font-family="DejaVu Sans Mono, Menlo, Consolas, monospace" font-size="%(fs)s">
    %(art)s
    </g>
    <g font-family="DejaVu Sans Mono, Menlo, Consolas, monospace">
      %(column)s
      <text x="%(rx)s" y="%(stamp)s" font-size="11" fill="#4c5865" letter-spacing="1.5">rebuilt %(today)s · numbers include private repositories</text>
    </g>
  </g>
</svg>
""" % {
        "w": width, "h": height, "alt": esc(alt).replace(NBSP, " "), "top": TOP, "artb": TOP + art_h,
        "fade": fade, "fs": round(fs, 2), "art": art, "column": "\n      ".join(column),
        "rx": right_x, "stamp": height - 46, "today": today,
    }


def main():
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("PROFILE_TOKEN")
    login = os.environ.get("USERNAME") or os.environ.get("GITHUB_REPOSITORY_OWNER")
    if not token or not login:
        print("need GITHUB_TOKEN and USERNAME", file=sys.stderr)
        return 1
    try:
        s = stats(fetch(token, login))
    except (urllib.error.URLError, RuntimeError, KeyError, TypeError) as e:
        print("could not build the numbers (%s) — keeping the existing panel" % e, file=sys.stderr)
        return 0
    svg = build(s, portrait_lines())
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(svg)
    print("wrote %s (%d bytes)" % (OUT, len(svg)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
