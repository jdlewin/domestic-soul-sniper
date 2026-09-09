# domestic-soul-sniper — Lean v1 Plan

**Status:** lean v1 implemented (smoke-verified 2026-08-13)  
**Date:** 2026-08-13  
**Scope:** agent-assisted photography toolkit for Fujifilm X-E3 monochrome (ACROS)

---

## Goal

End-to-end, agent-friendly pipeline:

**card/folder → import → neutral proof → cull → ACROS grade → metadata → print + web JPEGs**

Primary UX: CLI verbs + session folder + opencode chat driving the same commands.

---

## Decisions (locked)

| Area | Decision |
|------|----------|
| Project / repo | `domestic-soul-sniper` at `~/Projects/domestic-soul-sniper` |
| Camera | Fujifilm **X-E3** RAF only (first-class) |
| Look | **ACROS only** — one polished stock; default when `--stock` omitted |
| Color stocks | **Dropped** for lean v1 (Portra/Velvia/etc. later) |
| ACROS variants | Standard Acros only (no Ye/R filter stocks in lean) |
| Engines | **RawTherapee CLI** only (`rawtherapee-cli` 5.12 present) |
| darktable | Out of lean scope (`darktable-cli` not installed) |
| Layout | Date-based sessions under archive root |
| Cull | Before grade and/or after neutral proof; manual/external → `selects/` |
| Grade style | Global stock + exposure/WB pass (re-run after RT GUI sidecar tweaks) |
| Color management | Good enough **sRGB** out |
| Metadata | Copyright/creator profile, keywords, GPS add/strip; strip sensitive on export |
| Identity setup | **Prompt on first run** (and `photo setup`); store in user config |
| Exports | Full-res JPEG (print) + long-edge **2048** web JPEG |
| Samples | `~/Pictures/rawr/` (110× X-E3 RAF, in-camera Acros); smoke via `import --limit` |
| Defer | ML cull, GUI, client galleries, phone/HEIC, advanced retouch, second backup |

### Fuji film simulations

Ignore in-camera sims as the grade source of truth. Build ACROS as a RawTherapee PP3 on a neutral X-E3 base so the look is consistent and re-batchable. Sample RAFs are tagged `Saturation: Acros` for reference only.

---

## Verified environment

| Item | Value |
|------|--------|
| Samples | `~/Pictures/rawr/` — ~110 RAF, ~29G, Model X-E3, Saturation Acros |
| `rawtherapee-cli` | 5.12 |
| `exiftool` | 13.55 |
| X-E3 DCP | `/usr/share/rawtherapee/dcpprofiles/FUJIFILM X-E3.dcp` |
| Python | 3.14.x |
| Archive default | `~/Pictures/archive` |
| User config | `~/.config/domestic-soul-sniper/config.yaml` |

---

## Architecture

```
~/Projects/domestic-soul-sniper/          # this repo
~/.config/domestic-soul-sniper/           # identity, paths, defaults
~/Pictures/archive/YYYY/YYYY-MM-DD-slug/  # sessions
```

### Session on disk

```
2026-08-13-slug/
  session.yaml
  raw/                 # renamed RAF masters
  proof/neutral/       # fast cull JPEGs
  selects/             # optional keepers (stems); empty = process all
  export/print/        # full-res JPEG
  export/web/          # long-edge 2048 JPEG
  logs/
```

### Stack

Python 3 CLI (`photo`) → `rawtherapee-cli` → `exiftool`  
(ImageMagick only if needed later; not required for lean per-frame proofs.)

### Naming (import)

```
YYYYMMDD_HHMMSS_X-E3_DSCF####.RAF
```

From `DateTimeOriginal` + original basename. Stable, sortable, keeps camera id.

---

## CLI surface (frozen)

```text
photo setup
photo import <path> [--name SLUG] [--date YYYY-MM-DD] [--limit N]
photo proof  <session>
photo grade  <session> [--stock acros]    # default acros
photo meta   <session> [--keyword K]... [--gps LAT,LON | --strip-gps]
photo export <session>
photo status <session> [--json]
```

- **import** accepts card mount **or** folder (e.g. `~/Pictures/rawr`).
- **Never** modify or delete the source tree.
- **`--limit N`** for smoke imports during development.
- **selects/** non-empty → grade/export only matching stems; else all of `raw/`.

---

## Pipeline stages

1. **setup / first-run** — creator, copyright notice, optional contact, archive root; detect RT + exiftool.
2. **import** — copy RAF, rename, sha256 verify, init `session.yaml` + dirs.
3. **proof** — neutral fast JPEGs (`rawtherapee-cli -f`) into `proof/neutral/`.
4. **cull** — external/manual; optional `selects/`.
5. **grade** — PP3 stack `base-neutral-xe3` → `acros` on targets; sidecars allow exposure/WB re-batch.
6. **meta** — apply profile IPTC; session keywords; GPS add or strip policy.
7. **export** — print + web packs; strip GPS/serials (and similar) on delivery JPEGs.
8. **status** — human summary + `--json` for agents.

---

## Recipes (lean freeze)

```
recipes/rawtherapee/
  base-neutral-xe3.pp3    # X-E3-oriented neutral base (DCP/demosaic intent)
  acros.pp3               # only polished stock: B&W + Acros-like tone
recipes/exports/
  default.yaml            # print + web 2048 sRGB specs
```

**acros.pp3 quality bar:** usable Acros-like monochrome (forced B&W, gentle contrast curve, clean midtones; grain low/off to match typical in-camera off). Starting look—refine over time; structure supports re-batch.

**Not in lean:** acros-ye, acros-r, HP5/Tri-X, any color stock IDs.

---

## Proposed package layout

```
domestic-soul-sniper/
  pyproject.toml
  README.md
  PLAN.md                 # this document
  src/domestic_soul_sniper/
    __init__.py
    cli.py
    config.py
    session.py
    import_card.py
    proof.py
    grade.py
    meta.py
    export.py
    status.py
    engines/rawtherapee.py
  recipes/rawtherapee/
  recipes/exports/
  tests/                  # path/rename/session unit tests; no large RAF in git
```

Do **not** commit sample RAF binaries.

---

## Agent experience

Designed so opencode can drive without a GUI:

```text
photo import ~/Pictures/rawr --name smoke-xe3 --limit 5
photo proof  ~/Pictures/archive/2026/2026-…-smoke-xe3
photo grade  …
photo meta   … --keyword street
photo export …
photo status … --json
```

Chat maps to the same verbs; `session.yaml` + `status --json` are the machine API.

---

## Effort estimate (lean / under ~1M tokens)

| Slice | Work | Est. tokens |
|-------|------|-------------|
| A | Scaffold, config, session, CLI | 50–70k |
| B | Import folder/card, rename, verify, `--limit` | 70–100k |
| C | RT engine, neutral proof, acros PP3 + grade/selects | 120–160k |
| D | Meta + export print/web | 80–120k |
| E | Smoke on rawr subset, status JSON, README, edges | 80–120k |
| **Total** | | **~400–570k** |
| Buffer | Acros taste pass, EXIF edges | up to ~1M ceiling |

### Build order

1. Scaffold + `photo setup` / first-run config  
2. Import + rename + checksum + `--limit`  
3. RT wrapper + neutral proof on smoke session  
4. Author/tune `acros.pp3`; batch grade  
5. selects + export packs  
6. meta/strip + `status --json` + README  

---

## Out of scope (lean v1)

- darktable engine parity  
- ACROS Ye/R and other B&W/color stocks  
- ML culling, full GUI, client gallery uplink  
- HEIC/phone pipeline, advanced retouching  
- Soft-proof / complex ICC  
- Second backup destination, card wipe after import  
- Committing RAF fixtures into the repo  

---

## Done criteria

After smoke import from `~/Pictures/rawr --limit 5` (or similar):

1. Session exists under archive with renamed RAFs and checksums  
2. Neutral proofs written for cull  
3. `photo grade` (default acros) produces developed output path used by export  
4. `photo meta` applies profile; export strips sensitive tags  
5. `export/print/` full-res JPEG + `export/web/` ~2048 long-edge sRGB  
6. `photo status --json` reports stage/counts for an agent  

---

## Defaults

| Setting | Default |
|---------|---------|
| CLI name | `photo` |
| Default stock | `acros` |
| Archive root | `~/Pictures/archive` |
| Config dir | `~/.config/domestic-soul-sniper` |
| Import verify | sha256 on |
| Source safety | copy only; never delete card/folder sources |
