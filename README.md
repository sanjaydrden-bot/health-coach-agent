# The Health Coach – AI Content Agent

Roz ka health post (research → poster → Hindi awaaz wala Short) banata hai, dashboard pe approve hone ke baad YouTube (aur Meta connect hone par Instagram/Facebook) pe daalta hai.

## Kab kya chalta hai (IST)
| Time | Kaam |
|---|---|
| 07:00 (08:00 retry) | Research + aaj ka post → Google Sheet/Dashboard |
| Har 15 min (07:30–00:15) | Dashboard ki "Naya post" request + approved posts publish |
| 21:00 | YouTube performance + agle hafte ki strategy |

Haath se chalana ho: **Actions → Health Coach Agent → Run workflow** → task chuno.

## Secrets (Settings → Secrets and variables → Actions)
- `CONFIG_INI` – poori config.ini file ka text (keys, Sheet link)
- `YOUTUBE_TOKEN` – youtube_token.json file ka text

Keys kabhi code mein nahi daalni — sirf Secrets mein.
