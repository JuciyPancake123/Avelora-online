AVELORA COMBAT MANAGER — MAC LOCAL WI-FI EDITION
================================================
No Supabase. No Vercel. No Node.js. No cloud database.

WHAT YOU NEED
- A Mac (macOS) running Python 3.9 or newer.
- Your Mac and all three players on the SAME TRUSTED Wi-Fi network.
- Each player has a browser on a phone, tablet, or laptop.
- Internet is optional for playing; it is needed to search ALL official
  Pokémon and load their exact level-up moves from PokéAPI. The app includes
  an offline starter/Route 1 selection with approximate learn levels.

ONE-TIME SETUP (MAC)
1. Unzip the Avelora ZIP folder somewhere you can keep it, for example Documents.
2. If Python 3 isn't installed, download and install it from:
   https://www.python.org/downloads/macos/
   This is the only software dependency; you do NOT need Supabase, Vercel,
   a terminal package installation, GitHub or a cloud login.
3. Double-click START_Avelora.command.
   If macOS warns about an unidentified developer, right-click the file,
   choose Open, and confirm. If macOS won't execute it, open Terminal,
   type "chmod +x " (include the final space), drag the .command file
   into Terminal, and press Return. Then double-click again.
4. If macOS asks whether Python may accept incoming connections, choose Allow.
5. Your browser should open at http://localhost:8765. Click
   "Enter DM Dashboard". Only someone on the host Mac can sign in as DM.
6. The Terminal window shows the correct "Player URL" and six-character
   join code. Share both with your three players; don't guess the IP address.
7. Players open the Player URL in Safari/Chrome on the same Wi-Fi, enter the
   join code and their Trainer nicknames. Approve them in the DM dashboard.
8. Build each Pokémon, assign it to a Trainer, then set up a battle. Players
   can view only their own complete Pokémon sheets; opponents show approximate
   health only. During battles they enter their physical dice results.

DURING A SESSION
- Keep the Mac turned on and the START_Avelora Terminal window open.
- Closing the laptop or sleeping the Mac interrupts player connections.
- The browser refreshes automatically when the DM changes Pokémon or battles.
- The Mac stores all campaign data in data/avelora.sqlite3.
- Automatic backup snapshots are stored in data/backups/ (every 25 changes
  and at normal shutdown). Use DM Tools -> Backup at any time.
- DM Tools also has a JSON campaign export; keep backups outside the app
  folder as extra protection.
- When you finish, press Control+C in the Terminal window. Data saves safely.

ON SUBSEQUENT SESSIONS
Double-click START_Avelora.command again. Existing Pokémon, approved player
profiles, and battle progress automatically return. Player browsers retain
individual guest sessions unless cookies/browser data were cleared.

RULES (PRESERVED FROM COMBAT MANAGER v1.3)
- Natural Physical AC from CON/Defense, Special AC from WIS/Sp. Defense.
- Regular Pokémon max natural AC 17; eligible DM-approved legendary max 18.
- Natural AC changes on evolution / Mega form, not via ordinary level-ups;
  temporary combat effects may increase effective AC beyond the natural cap.
- HP, ability scores, and damage dice grow on your existing 5-level scale.
- STR Attack modifier and INT Special Attack modifier add damage.
- DEX Speed modifier adds to physical d20 initiative.
- Moves limited to four with remaining PP; searchable full Pokédex online,
  with level-legal randomized learnsets from a single game version.
- Each Pokémon has 1/4,096 natural shiny odds and DM force-shiny option.
- DM-approved Mega Evolution and Terastallization (maximum one of each per
  Trainer each battle, never both on one Pokémon).
- Player physical dice, 1v1 through 20v20, active bench/switching, status,
  type effectiveness, STAB, critical hits, and DM correction/undo controls.
- EXP is awarded to participating Pokémon; leveling follows v1.3 thresholds.
  Level-up moves can be chosen from the eligible list; evolution requires DM.
- Complex moves and rare abilities are still DM-adjudicated; not all official
  Pokémon mechanics are automated.

TROUBLESHOOTING
- Player cannot connect: confirm same Wi-Fi (not a guest network), exact IP
  and port, and macOS Firewall -> allow incoming connections for Python.
  Some routers use "client isolation", blocking devices on the same Wi-Fi.
- Host can't connect: another process may already be using port 8765.
  Close other instances first.
- Pokémon search fails: internet/PokéAPI connection required for complete
  official Pokédex. Try the offline quick-pick buttons instead.
- Players stay pending: approve each Trainer on the DM Overview.
- Player changed phones or cleared browser cookies: their old guest session
  will not transfer automatically. Ask DM to remove/reassign as needed.
- Running this over public Wi-Fi or the internet is NOT supported. The LAN
  connection is plain HTTP and is intended only for a trusted private network.
  Do not port-forward or expose port 8765 to the internet.

If you previously used the standalone v1.3 HTML app, its browser-local saves
are NOT automatically imported. Preserve your old HTML save backup.

Technical source files: server.py (Python HTTP + SQLite), rules.py (server-
authoritative Avelora mechanics), static/ (browser UI), offline_data.json.

ONLINE UPDATE: Player move changes and full party swaps now require DM approval. See START_HERE.md for the Online Edition instructions.
