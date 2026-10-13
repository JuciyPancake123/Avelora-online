# Avelora Combat Manager — Easy Online Edition

This edition uses **one live Railway web service** instead of the earlier Supabase + Vercel architecture. It reuses the server-authoritative Python/SQLite combat rules and browser dashboards from the local Wi-Fi edition. The server, website, streaming updates and SQLite data storage all run on Railway. **You do not have to run your Mac as a host.**

**Current status:** Source and local integration checks are prepared; **it has not been deployed to a real Railway project**. Your own GitHub and Railway setup, payment/usage decisions and end-to-end test are still required. A GitHub repository stores the code; Railway is the only hosting/backend service. The service may incur charges depending on your plan and usage. See https://railway.com/pricing.

## Fast setup (Mac or any desktop browser)

### 1. Upload the source to GitHub

1. Unzip `Avelora_Online_One_Service.zip`.
2. Go to https://github.com/new and create a **private** repository named `avelora-online`. Don't add a README or `.gitignore` during creation.
3. Choose **uploading an existing file** on the new repository page. Upload the **contents** of the `Avelora_Online_One_Service` folder (not the ZIP itself), preserving the `static/` folder. Commit the files.
4. Verify `Dockerfile`, `server.py`, `rules.py`, `offline_data.json`, `static/index.html`, `static/app.js`, and `static/style.css` appear in the repository. The included `tests/` and `START_HERE.md` are optional for the server but useful for troubleshooting.

If GitHub's web uploader does not preserve folder structure, upload the `static/` files into a `static` folder in the repository, or use GitHub Desktop to commit/publish the unzipped source.

### 2. Deploy in Railway

1. Open https://railway.com/new and create a project using **Deploy from GitHub repo**. Select your `avelora-online` repository. Railway uses the included `Dockerfile` and starts the Python server automatically.
2. In the Railway service **Variables**, add:

   | Name | Value |
   | --- | --- |
   | `AVELORA_DM_PASSWORD` | **Your own unique, secret password of at least 16 characters**, preferably a long randomly generated phrase. Never put it in GitHub or share it in chat. |
   | `AVELORA_ONLINE` | `1` (also supplied as a Docker default) |
   | `AVELORA_DATA_DIR` | `/data` (also supplied as a Docker default) |

   The app will refuse to start without a strong-enough DM password. A password change invalidates older DM login sessions after the server restarts.
3. **Crucial: add a Railway Volume attached to this service, mounted at `/data`.** The SQLite campaign database is stored there. **Do not start a real campaign until the volume is mounted**: without a volume, your saved campaign can disappear when Railway redeploys the container. Use **single replica only**; this server is intentionally a one-instance SQLite app.
4. Open the service **Settings → Networking → Generate Domain**. Your site should have an `https://...up.railway.app` address. You do not need to purchase a custom domain.
5. Wait for a successful deployment. Open the website address in your browser. If it fails, read the Railway service **Deploy Logs** for the startup error.

Railway docs: https://docs.railway.com/volumes and https://docs.railway.com/guides/flask (GitHub deployment and domain-generation steps also apply to this Python web server).

### 3. Enter as the DM, then invite your three players

1. On the website, enter your DM password. There is no DM email login or player account registration.
2. Open **Overview** and choose **Copy player invite link**. It includes the room code for convenience.
3. Send that single link to each of your three players. They open it on any device/network, enter a Trainer nickname, and request access.
4. You approve their requests in the DM Overview. They see only their own Pokémon sheets and limited opponent health/status details.
5. Open **Pokédex Builder** to make Pokémon and assign them to Trainers, then **Battle Board** to create battles.

## Player controls and DM approval queue (new)

Players can manage their own Pokémon **without gaining DM-level permissions**:

1. **Nickname:** Open **My Pokémon → choose Pokémon → Nickname** to rename your own Pokémon. Cosmetic nicknames save immediately.
2. **Move requests:** Open a Pokémon, select between one and four moves from its level-legal list, and choose **Request Move Change**. The currently equipped moves remain unchanged until the DM approves the proposed moves.
3. **Full party requests:** Open **Requests** and select up to six owned Pokémon for the party, including Pokémon currently in storage. Submit the complete party as one request—this supports direct swapping even if the party already has six Pokémon. The other owned Pokémon go to storage **only after DM approval**.
4. **Single transfers:** From a Pokémon sheet, use **Request move to Party / Storage** for a one-Pokémon transfer; use a full party request when swapping a full team.
5. **Combat control:** During the assigned turn, players still choose their own move, opponent and physical dice results, and can switch eligible Pokémon, within the established turn rules. Routine combat actions do not require an approval click each time; the DM can correct them.

The DM opens **Approvals** (or the request queue on **Overview**) to see which Trainer submitted the request, the requested moves or proposed team, and **Approve** or **Deny**. Denials can include a short reason. Both DM and players can review recent decisions. A request is validated again at approval time: if the Pokémon is no longer owned by the Trainer, a move has become illegal, or the affected Pokémon is in an ongoing battle, approval is rejected safely. Players cannot change other Trainers’ Pokémon or their own EXP, level, ownership, HP or evolutions.

**Important:** When a player submits a party or move request, they are *asking*, not changing the database. This version retains automatic online saves and private DM authentication. You may keep the previous locally hosted ZIP as a backup; this update keeps the same SQLite save schema and adds fields for approval history.

## Day-to-day usage

- **DM:** Full battle board, initiative, wild/NPC Pokémon, player approvals, EXP, edits, evolution, statuses, weather, HP, move/team/storage approvals, review history, Mega/Tera approval and overrides.
- **Players:** Their own Pokémon, move-change requests, complete team-swap requests, DM-approved party/storage edits, nickname edits, EXP/Bond readouts, live battle actions and physical dice entries. Opponent exact HP/AC, movesets and base stats remain private until appropriately revealed.
- **Live updates:** Server-sent events push version notifications; the browser also polls every nine seconds in case the stream reconnects. Reopening a browser restores the session if its cookies remain available.
- **Saves:** Each successful action commits to SQLite in the Railway Volume. The server keeps up to ten rotating SQLite backups (every 25 changes or a graceful stop). In **DM Tools → Export full campaign JSON**, download an additional manual backup to your own computer after each session.
- **Internet:** Required for the live app and for searching the full PokéAPI database. Included `offline_data.json` provides a limited backup Pokédex with approximate early-route learnsets.

## What the online build preserves

- v1.3-based STR/CON/INT/WIS/DEX/CHA/HP mapping; physical versus special AC; species/evolution determines natural AC, capped at 17 or 18 for DM-approved legendary Pokémon; HP and other attributes grow by level intervals.
- Four Pokémon moves, PP, level-legal randomized movesets, physical dice and move damage dice, type effectiveness, STAB, crits, initiative, switching, damage and status tracking, weather/terrain, EXP, server-side permissions and DM correction tools.
- Shiny chance 1/4096 (or DM override); Mega Evolution or Terastallization only for DM-approved Pokémon, one use per Trainer per battle for each transformation, never both transformations on the same Pokémon.
- One to 20 Pokémon per side, unequal sides supported; both active and benched Pokémon can be added.

**Limitations:** Unusual move effects, certain abilities, special evolution triggers and some edge cases still require DM adjudication. The level-legal move data depends on PokéAPI response availability. The original v1.3 browser save and the previous local Wi-Fi SQLite database are **not automatically imported** into this new online database. Keep older save exports.

## Important security and privacy guidance

- This version is for a small **private Pokémon D&D group**, not an open public community service. **Only the DM password permits DM access**. Choose a unique long password, enable strong security on your GitHub/Railway accounts and never paste passwords into this chat or commit them into the repo.
- The Railway-generated public domain uses HTTPS. DM/player session cookies are `HttpOnly`, `Secure`, and `SameSite=Strict`; actions are checked by the Python server, not merely by the UI. DM and player logins are protected against repeated wrong credential attempts. Player join requests need DM approval.
- Anyone with the link can see the **join form**, not your battle database. Do not post invitation links or room codes publicly; anyone with a room code may submit a join request.
- Don't run multiple Railway replicas with this SQLite + in-memory event architecture. Don't remove the `/data` volume. Set billing/usage limits or alerts in your hosting account if available.
- SQLite backups stored on a Railway volume are not a substitute for an independent backup; download JSON backups regularly.

## Troubleshooting

| Symptom | Action |
| --- | --- |
| Deployment fails immediately | Check `AVELORA_DM_PASSWORD` exists and is at least 16 characters. |
| Campaign resets after redeployment | Confirm Railway Volume is attached and mounted at `/data`, and you're on the same service and environment. |
| HTTPS site says unavailable | Check service logs, Networking → Generate Domain, and make sure one replica is running. |
| Players wait to join | DM must approve them from Overview. |
| Player access disappears after changing device | Player sessions are stored in each browser's cookies; that browser must rejoin and be approved again. |
| Moves/search unavailable | PokéAPI needs an internet connection; try the included starter/Route 1 fallback. |
| Sessions won't persist on mobile | Don't use private browsing or clear cookies; the secure session cookie is saved in the browser. |
| Changed the DM password | Existing DM sessions become invalid after deployment/restart; sign in using the new password. |

## Testing source code without deploying

On a machine with Python 3.9+, from the unzipped directory:

```bash
python3 -m unittest discover -s tests -v
```

These are local API/security checks simulating Railway's HTTPS proxy; they **do not** establish that a real Railway deployment works. The browser UI can be tested locally with `python3 server.py` (the ordinary host-only local mode) from the same folder, at `http://localhost:8765`. In local mode the DM uses the host computer, and the DM password form may accept any 16-character string; **online mode always requires the real server password**.

## Included files

- `server.py` — Python web server, authorization, save system, live events and battles.
- `rules.py` and `offline_data.json` — Avelora rules, type chart and fallback species/moves.
- `static/` — desktop DM and mobile Trainer dashboards.
- `Dockerfile`, `railway.json` — Railway-compatible build and health check.
- `.env.example` — names of variables (do not commit real passwords).
- `tests/test_online.py` — local server integration/security tests.
- `START_HERE.md` — this guide.
