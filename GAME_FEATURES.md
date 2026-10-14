# Avelora Online — Features and known limitations

This edition retains the prior one-service online game code. Only the deployment variable spelling and associated deployment guidance were corrected in this release.

- DM dashboard: complete Pokémon management, battle board, initiative, HP, EXP, evolution, Mega/Tera approval, and DM overrides.
- Player dashboards: individual Pokémon sheets, move requests, full-party/storage requests requiring DM approval, nicknames, physical dice battle actions, and live updates.
- Rules: STR/CON/INT/WIS/DEX/CHA/HP, separate physical and special AC, type effectiveness, STAB, critical hits, PP, statuses, level growth, shiny chance 1/4096, and battles up to 20v20.
- Storage: one Railway service with one replica; SQLite database and backups under `/data`, which **must** be a mounted persistent volume.
- Limitations: some uncommon moves, abilities, and evolution triggers still require DM adjudication; complete PokéAPI move data requires internet. Earlier standalone-browser save files are not automatically imported.
- The server is intended for a small private group, not an open public community. Protect your DM password and download manual campaign backups after sessions.

## Search / Rest / Level update

- Pokédex autocomplete with approximate spelling across PokéAPI names, and offline fallback.
- Starting level 1–100 is editable without reloading selected species; server rolls only level-legal moves.
- DM-only Short Rest and Long Rest (default 2× healing dice, adjustable 2–10×) with damage-scaled dice, trainer/individual/all scope, and rest audit history.
- Rest never revives a Pokémon at 0 HP and is blocked during an active battle.
- See UPDATE_GUIDE.md for exact dice formula and long-rest customization.
