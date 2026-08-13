# domestic-soul-sniper

Agent-assisted toolkit for Fujifilm X-E3 monochrome photography: import RAF, proof, ACROS grade, metadata, export JPEGs.

## Status

Lean v1 is **planned, not implemented**. See [PLAN.md](./PLAN.md).

## Intended CLI (v1)

```text
photo setup
photo import <path> [--name SLUG] [--date YYYY-MM-DD] [--limit N]
photo proof  <session>
photo grade  <session> [--stock acros]
photo meta   <session> [--keyword K]... [--gps LAT,LON | --strip-gps]
photo export <session>
photo status <session> [--json]
```

## License

TBD
