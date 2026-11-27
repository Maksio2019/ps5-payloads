#!/usr/bin/env python3
"""Rebuild payloads_v2.json from the latest GitHub release of every repo in sources.json.

Only payloads whose release changed are re-downloaded (to compute the SHA-256);
everything else is carried over from the existing payloads_v2.json.
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request

SOURCES = "sources.json"
OUTPUT = "payloads_v2.json"
UA = {"User-Agent": "ps5-payload-host-updater"}


def http_get(url, accept=None):
    headers = dict(UA)
    if accept:
        headers["Accept"] = accept
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return r.read()


def latest_release(repo):
    accept = "application/vnd.github+json"
    try:
        return json.loads(http_get(f"https://api.github.com/repos/{repo}/releases/latest", accept))
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
    # No "Latest" release (repo only publishes pre-releases): take the newest non-draft one.
    releases = json.loads(http_get(f"https://api.github.com/repos/{repo}/releases?per_page=10", accept))
    for rel in releases:
        if not rel.get("draft"):
            return rel
    raise RuntimeError("no releases found")


def pick_asset(assets, pattern):
    if pattern:
        rx = re.compile(pattern)
        matches = [a for a in assets if rx.search(a["name"])]
    else:
        matches = [a for a in assets if a["name"].lower().endswith((".elf", ".bin"))]
    return matches[0] if matches else None


def build_entry(src, release, asset, old):
    version = release["tag_name"]
    url = asset["browser_download_url"]
    if old and old.get("version") == version and old.get("url") == url and old.get("checksum"):
        checksum = old["checksum"]
        last_update = old.get("last_update")
        print(f"  {src['name']}: {version} unchanged")
    else:
        print(f"  {src['name']}: downloading {asset['name']} ({version})")
        checksum = hashlib.sha256(http_get(url)).hexdigest()
        last_update = (release.get("published_at") or "")[:10]

    entry = {
        "name": src["name"],
        "filename": asset["name"],
        "url": url,
        "source": f"https://github.com/{src['repo']}/releases",
        "source_direct": url,
        "description": src.get("description", ""),
        "last_update": last_update,
        "version": version,
        "category": src.get("category", "Utilities"),
        "checksum": checksum,
    }
    if src.get("icon_key"):
        entry["icon_key"] = src["icon_key"]
    return entry


def main():
    with open(SOURCES, encoding="utf-8") as f:
        sources = json.load(f)

    old_by_name = {}
    if os.path.exists(OUTPUT):
        with open(OUTPUT, encoding="utf-8") as f:
            old_by_name = {p["name"]: p for p in json.load(f).get("payloads", [])}

    payloads, failed = [], False
    for src in sources["payloads"]:
        old = old_by_name.get(src["name"])
        try:
            release = latest_release(src["repo"])
            asset = pick_asset(release.get("assets", []), src.get("asset_pattern"))
            if not asset:
                raise RuntimeError(f"no asset matched in release {release.get('tag_name')}")
            payloads.append(build_entry(src, release, asset, old))
        except Exception as e:
            failed = True
            print(f"  {src['name']}: ERROR {e}", file=sys.stderr)
            if old:  # keep the last good entry instead of dropping the payload
                payloads.append(old)

    catalog = {"name": sources.get("name", "My PS5 Payloads")}
    if sources.get("icons_url"):
        catalog["icons_url"] = sources["icons_url"]
    catalog["payloads"] = payloads

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {OUTPUT} with {len(payloads)} payload(s)")
    if failed and not payloads:
        sys.exit(1)


if __name__ == "__main__":
    main()
