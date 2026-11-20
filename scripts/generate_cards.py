#!/usr/bin/env python3
"""Render the profile stat cards straight from the GitHub GraphQL API.

Unlike github-readme-stats hosted on a shared Vercel instance, this runs with
the profile owner's token, so private contributions are counted too, and the
numbers can never be served stale by a third-party cache.

Outputs:
    assets/stats.svg      467x170  "Naster's GitHub Stats"
    assets/top-langs.svg  300x190  "Most Used Languages"

Environment:
    STATS_TOKEN  GitHub token with `repo` scope (falls back to GH_TOKEN).
"""

import datetime
import html
import json
import os
import sys
import urllib.request

LOGIN = "Naster17"
YEAR = datetime.date.today().year
EXCLUDE_REPOS = {"NetHunter-Kernels"}
HIDE_LANGS = {"perl", "astro", "typescript", "mdx", "scss", "javascript"}
LANG_COUNT = 8

API = "https://api.github.com/graphql"

# github_dark theme
BG = "#0D1117"
HEADER = "#58A6FF"
TEXT = "#C3D1D9"
ICON = "#1F6FEB"
FALLBACK_LANG_COLOR = "#858585"

ICONS = {
    "star": "M8 .25a.75.75 0 01.673.418l1.882 3.815 4.21.612a.75.75 0 01.416 1.279l-3.046 2.97.719 4.192a.75.75 0 01-1.088.791L8 12.347l-3.766 1.98a.75.75 0 01-1.088-.79l.72-4.194L.818 6.374a.75.75 0 01.416-1.28l4.21-.611L7.327.668A.75.75 0 018 .25zm0 2.445L6.615 5.5a.75.75 0 01-.564.41l-3.097.45 2.24 2.184a.75.75 0 01.216.664l-.528 3.084 2.769-1.456a.75.75 0 01.698 0l2.77 1.456-.53-3.084a.75.75 0 01.216-.664l2.24-2.183-3.096-.45a.75.75 0 01-.564-.41L8 2.694v.001z",
    "commits": "M1.643 3.143L.427 1.927A.25.25 0 000 2.104V5.75c0 .138.112.25.25.25h3.646a.25.25 0 00.177-.427L2.715 4.215a6.5 6.5 0 11-1.18 4.458.75.75 0 10-1.493.154 8.001 8.001 0 101.6-5.684zM7.75 4a.75.75 0 01.75.75v2.992l2.028.812a.75.75 0 01-.557 1.392l-2.5-1A.75.75 0 017 8.25v-3.5A.75.75 0 017.75 4z",
    "issues": "M8 1.5a6.5 6.5 0 100 13 6.5 6.5 0 000-13zM0 8a8 8 0 1116 0A8 8 0 010 8zm9 3a1 1 0 11-2 0 1 1 0 012 0zm-.25-6.25a.75.75 0 00-1.5 0v3.5a.75.75 0 001.5 0v-3.5z",
    "repo": "M2 2.5A2.5 2.5 0 014.5 0h8.75a.75.75 0 01.75.75v12.5a.75.75 0 01-.75.75h-2.5a.75.75 0 110-1.5h1.75v-2h-8a1 1 0 00-.714 1.7.75.75 0 01-1.072 1.05A2.495 2.495 0 012 11.5v-9zm10.5-1V9h-8c-.356 0-.694.074-1 .208V2.5a1 1 0 011-1h8zM5 12.25v3.25a.25.25 0 00.4.2l1.45-1.087a.25.25 0 01.3 0L8.6 15.7a.25.25 0 00.4-.2v-3.25a.25.25 0 00-.25-.25h-3.5a.25.25 0 00-.25.25z",
}

REPOS_QUERY = """
query($login: String!, $after: String, $forkFilter: Boolean) {
  user(login: $login) {
    repositories(first: 100, ownerAffiliations: [OWNER], after: $after, isFork: $forkFilter) {
      totalCount
      pageInfo { hasNextPage endCursor }
      nodes {
        name
        stargazers { totalCount }
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges { size node { name color } }
        }
      }
    }
  }
}
"""

STATS_QUERY = """
query($login: String!, $from: DateTime, $to: DateTime) {
  user(login: $login) {
    name
    login
    followers { totalCount }
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      restrictedContributionsCount
      totalPullRequestReviewContributions
    }
    pullRequests(first: 1) { totalCount }
    openIssues: issues(states: OPEN) { totalCount }
    closedIssues: issues(states: CLOSED) { totalCount }
    repositoriesContributedTo(
      first: 1
      contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]
    ) { totalCount }
  }
}
"""


def gql(query, variables):
    token = os.environ.get("STATS_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        sys.exit("STATS_TOKEN (or GH_TOKEN) is not set")
    req = urllib.request.Request(
        API,
        data=json.dumps({"query": query, "variables": variables}).encode(),
        headers={
            "Authorization": f"bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "Naster17-profile-cards",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            payload = json.load(resp)
    except urllib.error.HTTPError as exc:
        sys.exit(f"GitHub API error {exc.code}: {exc.read().decode(errors='replace')}")
    if "errors" in payload:
        sys.exit(f"GitHub API errors: {payload['errors']}")
    return payload["data"]


def fetch_repos(fork_filter):
    """fork_filter: None = owned repos incl. forks, False = non-fork repos only."""
    nodes, after = [], None
    while True:
        data = gql(
            REPOS_QUERY, {"login": LOGIN, "after": after, "forkFilter": fork_filter}
        )
        repos = data["user"]["repositories"]
        nodes.extend(repos["nodes"])
        if not repos["pageInfo"]["hasNextPage"]:
            return nodes
        after = repos["pageInfo"]["endCursor"]


def calculate_rank(commits, prs, issues, reviews, stars, followers):
    """Port of github-readme-stats' calculateRank (include_all_commits=false)."""
    commits_median, commits_weight = 250, 2
    prs_median, prs_weight = 50, 3
    issues_median, issues_weight = 25, 1
    reviews_median, reviews_weight = 2, 1
    stars_median, stars_weight = 50, 4
    followers_median, followers_weight = 10, 1
    total_weight = (
        commits_weight + prs_weight + issues_weight
        + reviews_weight + stars_weight + followers_weight
    )

    def exp_cdf(x):
        return 1 - 2 ** -x

    def log_normal_cdf(x):
        return x / (1 + x)

    rank = 1 - (
        commits_weight * exp_cdf(commits / commits_median)
        + prs_weight * exp_cdf(prs / prs_median)
        + issues_weight * exp_cdf(issues / issues_median)
        + reviews_weight * exp_cdf(reviews / reviews_median)
        + stars_weight * log_normal_cdf(stars / stars_median)
        + followers_weight * log_normal_cdf(followers / followers_median)
    ) / total_weight

    thresholds = [1, 12.5, 25, 37.5, 50, 62.5, 75, 87.5, 100]
    levels = ["S", "A+", "A", "A-", "B+", "B", "B-", "C+", "C"]
    percentile = rank * 100
    level = next(
        lvl for lvl, threshold in zip(levels, thresholds) if percentile <= threshold
    )
    return level, percentile


def fmt(value):
    return f"{value:,}"


def stat_row(y, icon, label, value):
    return f"""
      <g transform="translate(25, {y})">
        <svg class="icon" viewBox="0 0 16 16" width="16" height="16">
          <path fill-rule="evenodd" d="{ICONS[icon]}"/>
        </svg>
        <text class="stat" x="25" y="12.5">{html.escape(label)}</text>
        <text class="stat" x="219.01" y="12.5">{html.escape(value)}</text>
      </g>"""


def stats_svg(stats, name):
    circumference = 2 * 3.141592653589793 * 40
    offset = (1 - stats["percentile"] / 100) * circumference
    rows = "".join(
        stat_row(y, icon, label, value)
        for y, icon, label, value in [
            (0, "star", "Total Stars Earned:", fmt(stats["stars"])),
            (25, "commits", f"Total Commits ({YEAR}):", fmt(stats["commits"])),
            (50, "issues", "Total Issues:", fmt(stats["issues"])),
            (75, "repo", "Contributed to (last year):", fmt(stats["contributed_to"])),
        ]
    )
    return f"""<svg width="467" height="170" viewBox="0 0 467 170" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="titleId descId">
  <title id="titleId">{html.escape(name)}'s GitHub Stats, Rank: {stats["level"]}</title>
  <desc id="descId">Total Stars Earned: {stats["stars"]}, Total Commits in {YEAR}: {stats["commits"]}, Total Issues: {stats["issues"]}, Contributed to (last year): {stats["contributed_to"]}</desc>
  <style>
    .header {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {HEADER}; }}
    @supports(-moz-appearance: auto) {{ .header {{ font-size: 15.5px; }} }}
    .stat {{ font: 600 14px 'Segoe UI', Ubuntu, "Helvetica Neue", Sans-Serif; fill: {TEXT}; }}
    @supports(-moz-appearance: auto) {{ .stat {{ font-size: 12px; }} }}
    .rank-text {{ font: 800 24px 'Segoe UI', Ubuntu, Sans-Serif; fill: {TEXT}; }}
    .icon {{ fill: {ICON}; display: block; }}
    .rank-circle-rim {{ stroke: {HEADER}; fill: none; stroke-width: 6; opacity: 0.2; }}
    .rank-circle {{ stroke: {HEADER}; stroke-dasharray: 250; fill: none; stroke-width: 6; stroke-linecap: round; opacity: 0.8; transform-origin: -10px 8px; transform: rotate(-90deg); }}
  </style>
  <rect data-testid="card-bg" x="0.5" y="0.5" rx="4.5" height="99%" width="466" fill="{BG}" stroke="{BG}" stroke-opacity="0"/>
  <g data-testid="card-title" transform="translate(25, 35)">
    <text x="0" y="0" class="header">{html.escape(name)}'s GitHub Stats</text>
  </g>
  <g data-testid="main-card-body" transform="translate(0, 55)">
    <g data-testid="rank-circle" transform="translate(390.5, 35)">
      <circle class="rank-circle-rim" cx="-10" cy="8" r="40"/>
      <circle class="rank-circle" cx="-10" cy="8" r="40" stroke-dashoffset="{offset:.2f}"/>
      <text class="rank-text" x="-5" y="3" alignment-baseline="central" dominant-baseline="central" text-anchor="middle">{stats["level"]}</text>
    </g>{rows}
  </g>
</svg>
"""


def top_langs_svg(langs):
    total = sum(lang["bytes"] for lang in langs) or 1
    shown = langs[:LANG_COUNT]
    segments, x = [], 0.0
    for lang in shown:
        width = lang["bytes"] / total * 250
        segments.append(
            f'      <rect x="{x:.2f}" y="0" width="{width:.2f}" height="8" fill="{lang["color"]}"/>'
        )
        x += width
    bar = "\n".join(segments)

    legend = []
    for index, lang in enumerate(shown):
        column, row = divmod(index, 4)
        pct = lang["bytes"] / total * 100
        legend.append(
            f"""      <g transform="translate({column * 150}, {row * 25})">
        <circle cx="5" cy="6" r="5" fill="{lang["color"]}"/>
        <text x="15" y="10" class="lang-name">{html.escape(lang["name"])} {pct:.2f}%</text>
      </g>"""
        )
    legend = "\n".join(legend)

    return f"""<svg width="300" height="190" viewBox="0 0 300 190" fill="none" xmlns="http://www.w3.org/2000/svg" role="img" aria-labelledby="titleId">
  <title id="titleId">Most Used Languages</title>
  <style>
    .header {{ font: 600 18px 'Segoe UI', Ubuntu, Sans-Serif; fill: {HEADER}; }}
    @supports(-moz-appearance: auto) {{ .header {{ font-size: 15.5px; }} }}
    .lang-name {{ font: 400 11px "Segoe UI", Ubuntu, Sans-Serif; fill: {TEXT}; }}
  </style>
  <rect data-testid="card-bg" x="0.5" y="0.5" rx="4.5" height="99%" width="299" fill="{BG}" stroke="{BG}" stroke-opacity="0"/>
  <g data-testid="card-title" transform="translate(25, 35)">
    <text x="0" y="0" class="header">Most Used Languages</text>
  </g>
  <g data-testid="main-card-body" transform="translate(0, 55)">
    <g transform="translate(25, 0)">
      <mask id="rect-mask">
        <rect x="0" y="0" width="250" height="8" fill="white" rx="5"/>
      </mask>
      <g mask="url(#rect-mask)">
{bar}
      </g>
    </g>
    <g transform="translate(25, 25)">
{legend}
    </g>
  </g>
</svg>
"""


def main():
    year_start = f"{YEAR}-01-01T00:00:00Z"
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    data = gql(STATS_QUERY, {"login": LOGIN, "from": year_start, "to": now})["user"]
    contributions = data["contributionsCollection"]

    owned = fetch_repos(fork_filter=None)
    stars = sum(repo["stargazers"]["totalCount"] for repo in owned)

    commits = (
        contributions["totalCommitContributions"]
        + contributions["restrictedContributionsCount"]
    )
    issues = data["openIssues"]["totalCount"] + data["closedIssues"]["totalCount"]
    contributed_to = data["repositoriesContributedTo"]["totalCount"]

    level, percentile = calculate_rank(
        commits=commits,
        prs=data["pullRequests"]["totalCount"],
        issues=issues,
        reviews=contributions["totalPullRequestReviewContributions"],
        stars=stars,
        followers=data["followers"]["totalCount"],
    )

    display_name = data["name"] or data["login"]
    stats = {
        "stars": stars,
        "commits": commits,
        "issues": issues,
        "contributed_to": contributed_to,
        "level": level,
        "percentile": percentile,
    }

    languages = {}
    for repo in fetch_repos(fork_filter=False):
        if repo["name"] in EXCLUDE_REPOS:
            continue
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            if name.lower() in HIDE_LANGS:
                continue
            lang = languages.setdefault(
                name, {"bytes": 0, "color": edge["node"]["color"] or FALLBACK_LANG_COLOR}
            )
            lang["bytes"] += edge["size"]

    langs = sorted(
        ({"name": name, **value} for name, value in languages.items()),
        key=lambda lang: lang["bytes"],
        reverse=True,
    )

    os.makedirs("assets", exist_ok=True)
    with open("assets/stats.svg", "w", encoding="utf-8") as fh:
        fh.write(stats_svg(stats, display_name))
    with open("assets/top-langs.svg", "w", encoding="utf-8") as fh:
        fh.write(top_langs_svg(langs))

    print(
        f"stars={stars} commits={commits} issues={issues} "
        f"contributed_to={contributed_to} rank={level} ({percentile:.1f})"
    )
    print("top languages:", ", ".join(f"{l['name']} {l['bytes']}" for l in langs[:LANG_COUNT]))


if __name__ == "__main__":
    main()
