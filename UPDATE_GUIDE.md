# Avelora Online — Search, Rest, and Level Update

This update builds on the **10-player edition** and keeps the existing Railway project and SQLite database. No database reset is required.

## What's new

- **Pokédex search suggestions**: loads the full PokéAPI Pokémon name list in the DM builder, offers partial-name and typo-tolerant suggestions. Clicking a suggestion loads the official Pokémon and moves. When PokéAPI is unavailable, the offline starter list remains usable.
- **Level at creation**: set the creation level (1–100) in the DM builder. The selected level stays visible while you preview the legal moves. At creation the server randomly selects up to four level-up moves learned at or before the chosen level, and generates level-appropriate stats and HP. No TMs, egg moves, or tutor moves are auto-assigned.
- **DM Short Rest**: 1d4–5d12 depending on level and missing HP. Dice count = ceiling(5 × missing HP / maximum HP), limited to 1–5. Die size: level 1–19 d4, 20–39 d6, 40–59 d8, 60–79 d10, 80–100 d12. Healing never exceeds missing HP.
- **DM Long Rest (confirmed rule)**: roll more healing dice than a Short Rest using the same level- and missing-HP-based calculation. Default: **2× dice**, with DM-selectable **2–10× dice**. Healing is capped at the amount of missing HP; Long Rest does not guarantee full recovery. Optional PP restoration and ordinary status removal remain DM choices.
- DM may apply either rest to one Pokémon, a Trainer's entire collection (party and storage), or everyone. No rest during active battle. Pokémon at 0 HP cannot be revived by resting. Rest actions and dice results are saved in the DM-only rest history.

## Deploy to existing Railway service

1. **Back up your campaign first:** log into the existing Avelora site as DM → **DM Tools** → **Export full campaign JSON**.
2. In the GitHub repo already connected to Railway, update **`server.py`** and **`static/app.js`** with the versions in this package. These are the only two files required for the new features. Do not create a new repository or Railway service.
3. Commit both files to the branch Railway deploys, then check Railway → **Deployments**. Verify the latest commit is deployed successfully. If auto-deploy is not configured, use Railway's deployment controls to deploy the latest commit.
4. Hard-refresh the website (Mac: Cmd+Shift+R). Open **Pokédex Builder** for fuzzy search and level selection; open **DM Tools** for rest controls.
5. Keep the existing Railway `/data` volume and `AVELORA_*` variables unchanged. **Never commit your DM password.**

## Compatibility and limits

- Designed for the 10-player Avelora online code included in this ZIP. If your live GitHub repo differs from this baseline, review changes before replacing files.
- Fuzzy autocomplete requires a connection to PokéAPI to cover the full Pokédex. PokéAPI also supplies official move learnsets, which can differ by game version.
- This package was tested locally; it was **not automatically pushed to GitHub or deployed to Railway**.
