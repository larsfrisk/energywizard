"""Skip redundant branch checks only when an open PR covers this exact head."""
import json
import os
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def run_checks(event, ref, sha, repository, fetch):
    if event != "push" or not ref.startswith("refs/heads/") or ref == "refs/heads/main":
        return True
    query = urlencode({"state": "open", "head": repository.split("/")[0] + ":" + ref[11:], "per_page": 100})
    try:
        pulls = fetch(f"repos/{repository}/pulls?{query}")
        return not any(p.get("state") == "open" and p.get("head", {}).get("sha") == sha
                       and (p["head"].get("repo") or {}).get("full_name") == repository for p in pulls)
    except Exception:
        return True  # Lookup failure must run checks, never suppress validation.


def main():
    def fetch(path):
        req = Request(os.environ["GITHUB_API_URL"] + "/" + path,
                      headers={"Authorization": "Bearer " + os.environ["GH_TOKEN"],
                               "Accept": "application/vnd.github+json"})
        with urlopen(req, timeout=15) as response:
            return json.load(response)

    run = run_checks(os.environ["GITHUB_EVENT_NAME"], os.environ["GITHUB_REF"],
                     os.environ["GITHUB_SHA"], os.environ["GITHUB_REPOSITORY"], fetch)
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"run_checks={str(run).lower()}\n")


if __name__ == "__main__":
    main()
