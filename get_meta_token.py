"""Facebook Page + Instagram ka permanent token nikaal ke config.ini mein bharta hai."""
import configparser
import os

import requests

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = os.path.join(BASE, "config.ini")
cfg = configparser.ConfigParser()
cfg.read(CFG, encoding="utf-8")
V = cfg.get("settings", "GRAPH_VERSION", fallback="v25.0")
G = f"https://graph.facebook.com/{V}"

print("\n=== Facebook / Instagram connect ===\n")
app_id = input("App ID paste karein: ").strip()
app_secret = input("App Secret paste karein: ").strip()
short = input("Graph API Explorer wala User Token paste karein: ").strip()

r = requests.get(f"{G}/oauth/access_token", params={
    "grant_type": "fb_exchange_token", "client_id": app_id,
    "client_secret": app_secret, "fb_exchange_token": short}).json()
if "access_token" not in r:
    raise SystemExit(f"\nToken exchange fail: {r}")
long_user = r["access_token"]

pages = requests.get(f"{G}/me/accounts", params={
    "access_token": long_user, "fields": "id,name,access_token,instagram_business_account{id,username}"}).json()
data = pages.get("data", [])
if not data:
    raise SystemExit(f"\nKoi Facebook Page nahi mila: {pages}")

print("\nAapke Pages:")
for i, p in enumerate(data, 1):
    ig = p.get("instagram_business_account", {})
    print(f"  {i}. {p['name']}  (Instagram: @{ig.get('username', '-- linked nahi --')})")
pick = data[0]
for p in data:
    if "health coach" in p["name"].lower():
        pick = p
if len(data) > 1:
    n = input(f"\nKaunsa Page? number likhein [Enter = {pick['name']}]: ").strip()
    if n.isdigit():
        pick = data[int(n) - 1]

ig = pick.get("instagram_business_account")
if not ig:
    raise SystemExit("\nIs Page se Instagram Business/Creator account linked nahi hai. Pehle link karein.")

import re
text = open(CFG, encoding="utf-8").read()
for k, v in (("FB_PAGE_ID", pick["id"]), ("PAGE_ACCESS_TOKEN", pick["access_token"]),
             ("IG_USER_ID", ig["id"])):
    text = re.sub(rf"(?m)^{k}\s*=.*$", lambda m: f"{k} = {v}", text)
with open(CFG, "w", encoding="utf-8") as f:
    f.write(text)
print(f"\nHo gaya! Page: {pick['name']}  |  Instagram: @{ig.get('username')}")
print("Ye token expire nahi hoga (jab tak aap password ya permissions na badlein).")
