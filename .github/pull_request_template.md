## Asset

- Asset id: `assets/<asset-id>`
- Kind:
- New asset or update:

## Summary

What this asset is and the problem it solves.

## Checklist

- [ ] One asset in this pull request, in `assets/<asset-id>/`, with `manifest.yaml`, `README.md` and `CHANGELOG.md`.
- [ ] `python tools/assets.py validate` passes and `python tools/assets.py catalog` has been run.
- [ ] No customer names or data, internal links, unreleased product information or secrets (see [CONTRIBUTING.md](../CONTRIBUTING.md#public-safety-rules)).
- [ ] Samples use synthetic data; third-party content is MIT-compatible.
- [ ] For updates: `version` bumped, `CHANGELOG.md` entry added, `last_reviewed` updated.
