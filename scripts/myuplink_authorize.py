#!/usr/bin/env python3
"""Engångs-verktyg: hämtar en första refresh_token för myUplink (NIBE/Bosch/
Atlantic/Daikin-värmepumpar via molnet, se smartbox/drivers/heatpump_myuplink.py).

myUplink kräver en webbläsarbaserad inloggning + samtycke EN gång - det går inte
att automatisera headless. Så här gör du:

1. Skapa en applikation på https://dev.myuplink.com (Client Identifier + Client
   Secret). Ange "https://localhost/callback" som redirect-URI där.
2. Kör det här skriptet: MYUPLINK_CLIENT_ID=... MYUPLINK_CLIENT_SECRET=... \
   python3 scripts/myuplink_authorize.py
3. Öppna länken skriptet skriver ut i en webbläsare, logga in, godkänn.
4. Webbläsaren hamnar på en sida som inte laddar (localhost/callback) - det är
   okej, kopiera bara "code"-parametern ur adressfältet och klistra in den när
   skriptet frågar.
5. Skriptet sparar inloggningsuppgifterna i myuplink.env (eller --output FIL),
   en ny lokal fil med rättighet 0600. Flytta dem till din lokala .env utan att
   dela filen. Befintliga filer skrivs aldrig över och hemligheter skrivs inte ut.
"""
import os
import sys
import argparse
import json
import urllib.parse

import requests

CLIENT_ID = os.environ.get("MYUPLINK_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("MYUPLINK_CLIENT_SECRET", "")
REDIRECT_URI = os.environ.get("MYUPLINK_REDIRECT_URI", "https://localhost/callback")
SCOPE = "READSYSTEM WRITESYSTEM offline_access"


def save_credentials(path, refresh_token):
    """Create a private local env file without exposing tokens in terminal logs."""
    values = {"MYUPLINK_CLIENT_ID": CLIENT_ID, "MYUPLINK_CLIENT_SECRET": CLIENT_SECRET,
              "MYUPLINK_REFRESH_TOKEN": refresh_token}
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as target:
        for key, value in values.items():
            target.write(key + "=" + json.dumps(value) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Authorize myUplink and save credentials locally")
    parser.add_argument("--output", default="myuplink.env", help="New private env file (must not already exist)")
    args = parser.parse_args()
    if not (CLIENT_ID and CLIENT_SECRET):
        print("Sätt MYUPLINK_CLIENT_ID och MYUPLINK_CLIENT_SECRET (från dev.myuplink.com) först.")
        sys.exit(1)

    params = {
        "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT_URI,
        "scope": SCOPE,
    }
    print("Öppna den här länken i en webbläsare, logga in och godkänn:\n")
    print(f"https://api.myuplink.com/oauth/authorize?{urllib.parse.urlencode(params)}\n")
    code = input("Klistra in 'code'-parametern från omdirigerings-URL:en: ").strip()

    r = requests.post("https://api.myuplink.com/oauth/token", data={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
    }, timeout=10)
    r.raise_for_status()
    d = r.json()
    save_credentials(args.output, d["refresh_token"])
    print("\nKlart. Inloggningsuppgifterna är sparade i den lokala env-filen. Dela eller checka inte in filen.")


if __name__ == "__main__":
    main()
