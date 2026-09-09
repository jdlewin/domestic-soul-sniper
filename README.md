# domestic-soul-sniper

Agent-assisted toolkit for Fujifilm X-E3 monochrome photography: import RAF, proof, ACROS grade, metadata, export JPEGs.

## Status

Lean v1 is **implemented**. See [PLAN.md](./PLAN.md).

## Setup

```bash
cd ~/Projects/domestic-soul-sniper
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
photo setup
```

Requires `rawtherapee-cli`, `exiftool`, and (recommended) ImageMagick `magick` on PATH.

Config is stored at `~/.config/domestic-soul-sniper/config.yaml` (creator, copyright, archive root, tool paths).

## CLI reference

```text
photo setup
photo import <path> [--name SLUG] [--date YYYY-MM-DD] [--limit N]
photo proof  <session>
photo grade  <session> [--stock acros]
photo meta   <session> [--keyword K]... [--gps LAT,LON | --strip-gps]
photo export <session>
photo status <session> [--json]
```

`<session>` is the session directory path (the folder that contains `session.yaml`).

## Usage

### Typical shoot (CLI)

```bash
source ~/Projects/domestic-soul-sniper/.venv/bin/activate

# 1. Import from card or folder (never modifies the source)
photo import /run/media/$USER/CARD --name downtown-walk
# or from an existing folder, with a smoke limit while testing:
photo import ~/Pictures/rawr --name downtown-walk --limit 5

# Capture the session path from import output, or set it explicitly:
SESS=~/Pictures/archive/2025/2025-11-28-downtown-walk

# 2. Neutral proofs for culling
photo proof "$SESS"
# open $SESS/proof/neutral/ in a viewer

# 3. Optional cull: drop keeper stems (or empty marker files) into selects/
#    empty selects/ = process all raws
touch "$SESS/selects/DSCF5807"
touch "$SESS/selects/DSCF5808"

# 4. Grade (default stock: acros)
photo grade "$SESS"
# photo grade "$SESS" --stock acros

# 5. Metadata
photo meta "$SESS" --keyword street --keyword xe3
# photo meta "$SESS" --gps 37.7749,-122.4194
# photo meta "$SESS" --strip-gps

# 6. Export print + web packs
photo export "$SESS"
# print: $SESS/export/print/   (full-res)
# web:   $SESS/export/web/     (long edge 2048)

# 7. Status (human or JSON for agents)
photo status "$SESS"
photo status "$SESS" --json
```

### Import notes

| Flag | Meaning |
|------|---------|
| `--name SLUG` | Session folder slug (`YYYY-MM-DD-slug`) |
| `--date YYYY-MM-DD` | Override session date (default: first RAF `DateTimeOriginal`) |
| `--limit N` | Import at most N RAFs (dev/smoke) |

RAFs are renamed to:

```text
YYYYMMDD_HHMMSS_X-E3_DSCF####.RAF
```

Re-running import into the same session skips files that already match by sha256.

### Cull with selects

```bash
# process only two frames
rm -f "$SESS/selects/"*
touch "$SESS/selects/DSCF5807"
touch "$SESS/selects/DSCF5812"
photo grade "$SESS"
photo export "$SESS"

# clear selects to process everything again
rm -f "$SESS/selects/"*
```

Select entries can be bare stems (`DSCF5807`), full renamed stems, or dropped proof JPEGs — matching uses the stem.

### Smoke / regression

```bash
photo import ~/Pictures/rawr --name smoke-xe3 --limit 2
SESS=~/Pictures/archive/2025/2025-11-28-smoke-xe3   # use the path import prints
photo proof  "$SESS"
photo grade  "$SESS"
photo meta   "$SESS" --keyword street
photo export "$SESS"
photo status "$SESS" --json
```

### Usage with opencode

Run opencode from the repo (or any cwd) with the venv’s `photo` on PATH, or call the binary by absolute path.

```bash
cd ~/Projects/domestic-soul-sniper
source .venv/bin/activate
opencode
```

Ask the agent in natural language; it should drive the same CLI verbs and use `status --json` as the machine API.

**Example prompts**

```text
Import 3 RAFs from ~/Pictures/rawr as session smoke-xe3, then show status --json.
```

```text
Proof and grade the latest smoke-xe3 session under ~/Pictures/archive. Default stock acros.
```

```text
For session ~/Pictures/archive/2025/2025-11-28-utest-xe3:
- apply meta keywords street, xe3
- export print + web
- report status --json and summarize counts
```

```text
Cull session $SESS to only DSCF5807 and DSCF5808 (use selects/), then re-grade and export.
```

```text
Sitrep on photography pipeline: is lean v1 done? What command runs a 2-frame smoke?
```

**Agent conventions**

1. Prefer real absolute session paths (never leave globs unexpanded).
2. After each stage, run `photo status <session> --json` and read `stages` / `counts`.
3. Do not modify or delete files under the import source tree.
4. Do not commit RAF binaries.
5. Re-runs are safe: import skips identical checksums; grade/export overwrite outputs.

**Minimal agent loop**

```text
photo import <src> --name <slug> [--limit N]
photo status <session> --json          # confirm imported
photo proof <session>
photo grade <session>                  # after optional selects/
photo meta <session> --keyword …
photo export <session>
photo status <session> --json          # all stages true
```

## Session layout

```text
~/Pictures/archive/YYYY/YYYY-MM-DD-slug/
  session.yaml
  raw/                 # renamed RAF masters
  proof/neutral/       # fast cull JPEGs
  selects/             # optional keepers (stems); empty = all
  graded/              # full-res ACROS JPEGs
  export/print/        # full-res delivery JPEGs
  export/web/          # long-edge 2048 JPEGs
  logs/
```

## Recipes

- `recipes/rawtherapee/base-neutral-xe3.pp3` — neutral X-E3 base
- `recipes/rawtherapee/acros.pp3` — B&W ACROS-like stock
- `recipes/exports/default.yaml` — print + web 2048

## Tests

```bash
source .venv/bin/activate
pytest -q
```

## License

TBD
