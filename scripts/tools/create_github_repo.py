"""
Create the GitHub repository via the GitHub API.

Set GITHUB_TOKEN in the environment before running this one-off tool.
"""
import os
import sys

import requests


GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
REPO_NAME = os.environ.get("GITHUB_REPO_NAME", "irontrader3")

if not GITHUB_TOKEN:
    print("[FAIL] Missing GITHUB_TOKEN environment variable")
    sys.exit(1)

headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",
}

data = {
    "name": REPO_NAME,
    "description": "IronTrader 3.0 - Stock Trading System with Chip Quality Scoring",
    "private": False,
    "auto_init": False,
}

print(f"Creating repository: {REPO_NAME}...")
response = requests.post("https://api.github.com/user/repos", headers=headers, json=data, timeout=30)

if response.status_code == 201:
    repo_data = response.json()
    print("[OK] Repository created successfully!")
    print(f"   URL: {repo_data['html_url']}")
    print(f"   Clone URL: {repo_data['clone_url']}")
else:
    print("[FAIL] Failed to create repository")
    print(f"   Status code: {response.status_code}")
    print(f"   Error: {response.text}")
    sys.exit(1)
