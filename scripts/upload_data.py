#!/usr/bin/env python3
"""Push usage-data exports (or a tierlist CSV) into a running Credit Usage
Explorer — the scriptable version of the Summary-page / Settings uploaders,
for cron jobs or a one-liner after downloading a fresh export.

Uses only the Python standard library, so it runs anywhere the app does.

Examples
--------
# Merge one or more usage exports into the running app:
python scripts/upload_data.py export1.csv export2.xlsx

# Replace the current data instead of merging:
python scripts/upload_data.py --replace fresh_export.csv

# Import a tierlist (users export with a groups column):
python scripts/upload_data.py --tierlist "BNL users export.csv"

# Download from a URL first (e.g. a signed export link), then upload:
python scripts/upload_data.py --download-from "https://.../export.csv" \
    --header "Authorization: Bearer $TOKEN"

# Target a non-default host:
python scripts/upload_data.py --url http://myhost:5000 export.csv

curl equivalent (usage data):
  curl -L -F "file=@export.csv" http://127.0.0.1:5000/upload-data
curl equivalent (tierlist):
  curl -L -F "file=@users.csv" -F "import_mode=merge" http://127.0.0.1:5000/settings/tiers/import
"""
from __future__ import annotations

import argparse
import http.cookiejar
import mimetypes
import re
import sys
import tempfile
import urllib.request
import uuid
from pathlib import Path


def build_multipart(fields: dict[str, str], files: list[Path]) -> tuple[bytes, str]:
    """Encode form fields + files as multipart/form-data (stdlib only)."""
    boundary = f"----cue-upload-{uuid.uuid4().hex}"
    lines: list[bytes] = []
    for name, value in fields.items():
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="{name}"'.encode(),
            b"",
            str(value).encode(),
        ]
    for path in files:
        ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        lines += [
            f"--{boundary}".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{path.name}"'.encode(),
            f"Content-Type: {ctype}".encode(),
            b"",
            path.read_bytes(),
        ]
    lines += [f"--{boundary}--".encode(), b""]
    return b"\r\n".join(lines), f"multipart/form-data; boundary={boundary}"


def flash_messages(html: str) -> list[str]:
    """Pull the app's flash messages out of the redirected-to page."""
    found = re.findall(r'class="alert alert-[a-z]+[^"]*"[^>]*>(.*?)</div>', html, re.S)
    cleaned = []
    for block in found:
        text = re.sub(r"<[^>]+>", " ", block)
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            cleaned.append(text)
    return cleaned


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path, help="export files to upload (.csv/.xlsx/.xls)")
    ap.add_argument("--url", default="http://127.0.0.1:5000", help="base URL of the running app")
    ap.add_argument("--replace", action="store_true", help="replace current data instead of merging")
    ap.add_argument("--tierlist", action="store_true", help="upload to the tierlist importer instead of usage data")
    ap.add_argument("--tierlist-mode", choices=["merge", "replace"], default="merge",
                    help="tierlist import mode (default: merge)")
    ap.add_argument("--download-from", metavar="URL", help="download this URL to a temp file and upload it")
    ap.add_argument("--header", action="append", default=[], metavar="'Name: value'",
                    help="extra header for --download-from (repeatable, e.g. auth)")
    args = ap.parse_args()

    files = list(args.files)
    if args.download_from:
        req = urllib.request.Request(args.download_from)
        for h in args.header:
            name, _, value = h.partition(":")
            req.add_header(name.strip(), value.strip())
        with urllib.request.urlopen(req, timeout=120) as resp:
            suffix = Path(args.download_from.split("?")[0]).suffix or ".csv"
            tmp = Path(tempfile.gettempdir()) / f"cue_download_{uuid.uuid4().hex}{suffix}"
            tmp.write_bytes(resp.read())
            print(f"downloaded {tmp.stat().st_size:,} bytes -> {tmp}")
            files.append(tmp)

    if not files:
        ap.error("no files to upload (pass paths and/or --download-from)")
    for path in files:
        if not path.exists():
            print(f"error: {path} does not exist", file=sys.stderr)
            return 2

    if args.tierlist:
        endpoint = f"{args.url.rstrip('/')}/settings/tiers/import"
        fields = {"import_mode": args.tierlist_mode}
        if len(files) > 1:
            print("error: tierlist import takes exactly one CSV", file=sys.stderr)
            return 2
    else:
        endpoint = f"{args.url.rstrip('/')}/upload-data"
        fields = {"replace_existing": "on"} if args.replace else {}

    body, content_type = build_multipart(fields, files)
    req = urllib.request.Request(endpoint, data=body, method="POST")
    req.add_header("Content-Type", content_type)
    # Flash messages ride the session cookie across the POST->redirect->GET,
    # so a cookie-aware opener is required to read the outcome.
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
    )
    with opener.open(req, timeout=300) as resp:
        html = resp.read().decode("utf-8", errors="replace")
        print(f"{endpoint} -> HTTP {resp.status}")

    for message in flash_messages(html) or ["(no status message found — check the app UI)"]:
        print(" ", message)
    return 0


if __name__ == "__main__":
    sys.exit(main())
