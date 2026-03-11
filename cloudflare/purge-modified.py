#!/usr/bin/env python3
"""
Cloudflare cache purge tool based on content hash comparison.

Usage:
    python purge-modified.py \
        --public-dir ./public \
        --base-url https://example.com \
        --zone-id <your_zone_id> \
        --api-token <your_api_token> \
        [--prev-manifest public_manifest] \
        [--save-manifest public_manifest_new] \
        [--batch-size 30] \
        [--full-purge]
"""

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

def hash_public_dir(public_dir: Path) -> list[tuple[str, str]]:
    files = []
    for path in public_dir.rglob("*"):
        if path.is_file():
            rel_path = path.relative_to(public_dir).as_posix()
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            files.append((digest, rel_path))
    return sorted(files, key=lambda e: e[1])

def load_manifest(path: Path) -> set[str]:
    return set(path.read_text(encoding="utf-8").splitlines()) if path.exists() else set()

def write_manifest(path: Path, entries: list[tuple[str, str]]):
    path.write_text("".join(f"{d}  {p}\n" for d, p in entries), encoding="utf-8")

def diff_files(current: list[tuple[str, str]], previous_lines: set[str]) -> list[str]:
    current_lines = {f"{d}  {p}" for d, p in current}
    return sorted(line.split("  ", 1)[1] for line in (current_lines - previous_lines))

def build_urls(files: list[str], base_url: str) -> list[str]:
    base = base_url.rstrip("/")
    urls = []
    for f in files:
        quoted = urllib.parse.quote(f)
        urls.append(f"{base}/{quoted}")
        # Cloudflare caches directory URLs and index.html URLs as separate keys.
        # Browsers request the directory form (e.g., /leadership/), so we must
        # purge that in addition to the file path form.
        if f.endswith("/index.html"):
            urls.append(f"{base}/{quoted[:-len('index.html')]}")
        elif f == "index.html":
            urls.append(f"{base}/")
    return urls

def purge_cloudflare(zone_id: str, api_token: str, urls: list[str], batch_size: int = 30):
    headers = {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }

    if not urls:
        print("✅ No files changed. No purge needed.")
        return

    print(f"📦 Purging {len(urls)} URLs in batches of {batch_size}")

    for i in range(0, len(urls), batch_size):
        batch = urls[i:i + batch_size]
        payload = json.dumps({"files": batch}).encode("utf-8")
        print(f"➡️  Sending batch {i // batch_size + 1} ({len(batch)} URLs)")
        for url in batch[:3]:
            print(f"   ↳ {url}")
        req = urllib.request.Request(
            url=f"https://api.cloudflare.com/client/v4/zones/{zone_id}/purge_cache",
            data=payload,
            headers=headers,
            method="POST"
        )
        try:
            with urllib.request.urlopen(req) as res:
                body = res.read().decode("utf-8")
                print(f"✅ Batch {i // batch_size + 1} sent. Status: {res.status}")
                print(f"   ↳ Response: {body}")
            time.sleep(0.5)  # throttle slightly
        except Exception as e:
            print(f"❌ Failed to purge batch {i // batch_size + 1}: {e}")
            raise

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--public-dir", type=Path, required=True)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--zone-id", required=True)
    parser.add_argument("--api-token", required=True)
    parser.add_argument("--prev-manifest", type=Path, default=Path("public_manifest"))
    parser.add_argument("--save-manifest", type=Path, default=Path("public_manifest_new"))
    parser.add_argument("--batch-size", type=int, default=30)
    parser.add_argument("--full-purge", action="store_true")

    args = parser.parse_args()

    if not args.public_dir.exists():
        print(f"❌ ERROR: public directory '{args.public_dir}' does not exist.")
        sys.exit(1)

    current = hash_public_dir(args.public_dir)
    previous_lines = load_manifest(args.prev_manifest)

    if args.full_purge or not previous_lines:
        if args.full_purge:
            print("⚠️  Purge entire cache due argument `--full-purge`")
        elif not previous_lines:
            print(f"⚠️  Purge entire cache because the previous manifest `{args.prev_manifest}` does not exist or is invalid")
        changed_files = [p for _, p in current]
    else:
        changed_files = diff_files(current, previous_lines)

    urls = build_urls(changed_files, args.base_url)
    purge_cloudflare(args.zone_id, args.api_token, urls, args.batch_size)

    write_manifest(args.save_manifest, current)

if __name__ == "__main__":
    main()
