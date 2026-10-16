#!/usr/bin/env python3
"""
asset-inspect.py — deterministic anatomy of a candidate repo, for the asset-audit worker.

Read-only by construction: every fact comes from the GitHub REST API via `gh api` (authenticated as
BladeRunner28). It never clones, never installs, never executes candidate code, and never touches a
key — which is what makes it safe to run unattended on unknown repos.

The point is to remove the "README says it does X" problem: the anatomy puts claim size next to code
size, lists the licence/activity/test/CI facts, and greps for key requirements and telemetry, so the
audit's judgement is made on structure, not marketing.

Usage: python3 scripts/asset-inspect.py --repo owner/name [--max-readme 3000]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict
from typing import Any

KEY_PAT = ("private_key", "privatekey", "api_key", "apikey", "secret", "mnemonic",
           "seed_phrase", "seedphrase", "wallet", "passphrase", "token")
TELEMETRY_PAT = ("posthog", "sentry", "telemetry", "analytics", "mixpanel", "amplitude",
                 "datadog", "google-analytics")
HYPE_PAT = ("guaranteed", "risk-free", "riskless", "free money", "100% win", "can't lose",
            "prints money", "profit daily", "secret strategy")
STUB_PAT = ("todo", "not implemented", "notimplemented", "stub", "coming soon", "placeholder",
            "work in progress", "wip")
MF_MAP = {".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript",
          ".rs": "rust", ".go": "go", ".java": "java", ".rb": "ruby", ".sol": "solidity",
          ".sql": "sql", ".md": "markdown", ".ipynb": "notebook"}
NOTES = {"license_file": "README/LICENSE check", "tests": "tests/ or test_*.py present",
         "ci": "GitHub Actions workflow", "env_example": ".env.example (keyed setup)",
         "docker": "Dockerfile (runnable image)", "lock": "lockfile (pinned deps)"}


def gh(path: str) -> Any | None:
    try:
        p = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=45)
    except Exception as e:  # noqa: BLE001
        print(f"  - gh failed: {type(e).__name__}: {e}", file=sys.stderr)
        return None
    if p.returncode != 0:
        print(f"  - gh api {path} -> exit {p.returncode}: {p.stderr.strip()[:120]}", file=sys.stderr)
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


def gh_raw(path: str) -> str | None:
    try:
        p = subprocess.run(["gh", "api", path, "-H", "Accept: application/vnd.github.raw"],
                           capture_output=True, text=True, timeout=45)
    except Exception:  # noqa: BLE001
        return None
    return p.stdout if p.returncode == 0 else None


def hits(text: str, pats: tuple[str, ...]) -> list[str]:
    low = text.lower()
    return sorted({p for p in pats if p in low})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--max-readme", type=int, default=3000)
    a = ap.parse_args()

    meta = gh(f"repos/{a.repo}")
    if meta is None:
        print(f"**SOURCE FAILED — repos/{a.repo}**: not reachable (private, renamed, or rate-limited)")
        return 1

    out: list[str] = [f"# Anatomy — `{a.repo}`", ""]
    lic = (meta.get("license") or {}).get("spdx_id") or "no-licence"
    out.append(f"- **Stars/forks/issues:** ★{meta.get('stargazers_count')} · forks {meta.get('forks_count')} · "
               f"open issues {meta.get('open_issues_count')} · watchers {meta.get('subscribers_count')}")
    out.append(f"- **Licence:** {lic} · **archived:** {bool(meta.get('archived'))} · "
               f"**created:** {(meta.get('created_at') or '')[:10]} · **last push:** {(meta.get('pushed_at') or '')[:10]} · "
               f"**size:** {meta.get('size')} KB · **default branch:** {meta.get('default_branch')}")
    if meta.get("description"):
        out.append(f"- **Description:** {meta['description'][:200]}")
    if meta.get("topics"):
        out.append(f"- **Topics:** {', '.join(meta['topics'][:12])}")
    out.append(f"- **URL:** {meta.get('html_url')}")

    langs = gh(f"repos/{a.repo}/languages")
    if isinstance(langs, dict) and langs:
        tot = sum(langs.values()) or 1
        top = sorted(langs.items(), key=lambda kv: -kv[1])[:5]
        out.append("- **Languages:** " + ", ".join(f"{k} {v * 100 // tot}%" for k, v in top))

    branch = meta.get("default_branch") or "main"
    tree = gh(f"repos/{a.repo}/git/trees/{branch}?recursive=1")
    paths: list[str] = []
    if isinstance(tree, dict) and "tree" in tree:
        paths = [e["path"] for e in tree["tree"] if e.get("type") == "blob"]
        by_ext: dict[str, list[int]] = defaultdict(list)
        for e in tree["tree"]:
            if e.get("type") != "blob":
                continue
            ext = "." + e["path"].rsplit(".", 1)[-1].lower() if "." in e["path"].rsplit("/", 1)[-1] else "(none)"
            by_ext[ext].append(e.get("size") or 0)
        out.append(f"- **Files:** {len(paths)} · **tree truncated:** {bool(tree.get('truncated'))} · "
                   f"**code bytes by type:** " + ", ".join(
                       f"{k} {sum(v) / 1024:.0f}KB/{len(v)}f"
                       for k, v in sorted(by_ext.items(), key=lambda kv: -sum(kv[1]))[:6]))
        low = " ".join(paths).lower()
        flags = {
            "tests": any("test" in p.lower() for p in paths),
            "ci": any(p.startswith(".github/workflows/") for p in paths),
            "env_example": any(".env.example" in p or ".env.sample" in p for p in paths),
            "docker": any(p.lower().startswith("dockerfile") for p in paths),
            "lock": any(p.lower().endswith(("poetry.lock", "package-lock.json", "uv.lock",
                                            "cargo.lock", "go.sum", "requirements.txt")) for p in paths),
        }
        out.append("- **Structure:** " + " · ".join(f"{k}={'yes' if v else 'NO'}" for k, v in flags.items()))
        manifests = [p for p in paths if p.lower().rsplit("/", 1)[-1] in
                     ("pyproject.toml", "setup.py", "requirements.txt", "package.json", "cargo.toml",
                      "go.mod", "dockerfile")]
        if manifests:
            out.append(f"- **Manifests:** {', '.join(manifests[:8])}")
        entries = [p for p in paths if p.lower().rsplit("/", 1)[-1] in
                   ("main.py", "app.py", "cli.py", "index.ts", "main.rs", "main.go", "__main__.py",
                    "server.py", "bot.py")]
        if entries:
            out.append(f"- **Likely entrypoints:** {', '.join(entries[:6])}")
        junk = [p for p in paths if "__pycache__" in p or p.endswith((".pyc", ".lock.bak"))]
        if junk:
            out.append(f"- **Repo hygiene:** {len(junk)} committed cache/artifact files "
                       f"(e.g. {junk[0]}) — a smell, not a blocker")

    commits = gh(f"repos/{a.repo}/commits?per_page=5")
    if isinstance(commits, list) and commits:
        out.append("- **Recent commits:** " + " · ".join(
            f"{(c.get('commit', {}).get('author', {}) or {}).get('date', '')[:10]} "
            f"{(c.get('commit', {}).get('message', '') or '').splitlines()[0][:52]}" for c in commits[:4]))
    rel = gh(f"repos/{a.repo}/releases?per_page=2")
    if isinstance(rel, list) and rel:
        out.append("- **Latest releases:** " + ", ".join(
            f"{r.get('tag_name')} ({(r.get('published_at') or '')[:10]})" for r in rel))

    readme = gh_raw(f"repos/{a.repo}/readme")
    if readme:
        body = readme[: a.max_readme]
        words = len(readme.split())
        out.append("")
        out.append(f"## README signal (full length {words} words; first {len(body)} chars shown)")
        claimed_keys = hits(body, KEY_PAT)
        telemetry = hits(body, TELEMETRY_PAT)
        hype = hits(body, HYPE_PAT)
        stubs = hits(body, STUB_PAT)
        out.append(f"- **Key/secret requirements mentioned:** {', '.join(claimed_keys) or 'none'}")
        out.append(f"- **Telemetry/analytics mentioned:** {', '.join(telemetry) or 'none'}")
        out.append(f"- **Hype markers:** {', '.join(hype) or 'none'}")
        out.append(f"- **Stub/incomplete markers:** {', '.join(stubs) or 'none'}")
        out.append("")
        out.append("```")
        out.extend(body.splitlines()[:45])
        out.append("```")
    else:
        out.append("- **SOURCE FAILED — README**: not fetched (empty, or API error)")

    out.append("")
    out.append("## How to use this")
    out.append("- Claim-vs-substance: compare README length and language against code bytes/files above; "
               "a large README over a 20-KB tree is a claim, not a system.")
    out.append("- A `key=yes`-style README requirement means it cannot be adopted for the live lane "
               "(our never-handle-keys rule); note it and stop.")
    out.append("- No licence = read-for-ideas only, never vendor or copy code.")
    print("\n".join(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
