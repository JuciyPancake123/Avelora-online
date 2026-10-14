# Avelora Online — Battle Testing Quality-of-Life Update

This release builds on the 10-player Avelora Online edition with fuzzy search, level-specific creation, and Short/Long Rest rules.

## Changes

1. **Armor Class clarified.** `AC 16/14` means 16 Physical Armor Class and 14 Special Armor Class, with a visible explanation and hover help.
2. **Weather and terrain redesign.** Colored status panels show current conditions and their effects on combat.
3. **Animated HP bars.** HP gains and losses smoothly change bar length during live updates (respects reduced-motion settings).
4. **Add a Trainer's full party.** The battle setup screen offers `+ Trainer party` buttons for approved Trainers with healthy equipped Pokémon; max 20 per side remains.
5. **Enemy reserve privacy.** The server omits inactive enemy Pokémon from player data entirely, including initiative order. DM overrides on hidden enemy reserves stay hidden until those Pokémon appear. DM still sees all Pokémon.
6. **Initiative input persists.** The saved base roll and calculated initiative total remain visible after clicking Set.
7. **Switching clarified.** Use `Switch Now` on your active Pokémon's turn to substitute a healthy same-Trainer reserve (consumes that action). When an active Pokémon faints, the Trainer or DM can use `Send Out` to replace it without an additional turn.
8. **Bulk delete.** All Pokémon → Mass delete Pokémon. You can choose multiple Pokémon; only the DM can delete, and Pokémon in an ongoing battle are protected. Export a backup before deleting.
9. **Trainer rosters.** DM Tools → Trainer Rosters shows each Trainer's equipped party (up to six) and stored Pokémon. DM/wild Pokémon have their own section.
10. **No artificial game cap on initiative totals or damage-dice sums.** Inputs accept custom nonnegative integers, with basic 15-digit numerical-size validation for server safety. Individual **d20 hit dice** still use 1–20 for normal hit/critical rules. The total roll is not capped to the expected dice count or sides.

## Update your deployed Railway app

1. **Export a backup** from Avelora's DM Tools (`Export full campaign JSON`).
2. Keep your existing Railway service, environment variables, and `/data` persistent volume.
3. In the existing GitHub repository, replace these **three files** while keeping their paths intact:
   - `server.py` (repository root)
   - `static/app.js`
   - `static/style.css`
4. Commit the changes to the branch Railway deploys (usually `main`).
5. Open Railway → your service → Deployments and verify the new GitHub commit is deployed and marked Active.
6. Hard refresh the site if you still see the old interface (Mac: Command + Shift + R).

**Do not replace the persistent SQLite database or delete the Railway volume.** This update changes code and styles, not the stored campaign schema.

## Test checklist

- DM Tools displays Trainer Rosters for existing players.
- All Pokémon has a Mass delete section. Try selecting 2 test Pokémon before using on live campaign content.
- Battle Setup → `+ Trainer party` adds the Trainer's healthy equipped party Pokémon to that side.
- Players can see active opponents, but not the opponent's benched Pokémon.
- Initiative `Set` retains the entered roll.
- Attack dice sums can exceed normal dice maximums without being rejected.
- Player and DM can switch the current combatant to a same-Trainer healthy reserve; fainted Pokémon have a replacement control.
- Weather and terrain conditions show distinct colored panels; HP bars animate after combat.

## Validation

`python -m unittest discover -s tests -v`

The suite includes online multiplayer access, 10-player join tests, concealment of benched enemy Pokémon and their override logs, saved initiative rolls, switching, fainted replacement, damage-dice sums exceeding normal roll limits, and DM-only bulk deletion.
