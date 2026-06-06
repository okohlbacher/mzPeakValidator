# Validation profiles

One reference page per profile, describing its checks and rule structure: conformance
axes, severity/recovery model, pinned artifacts, every rule (id / primitive / severity /
recovery / what it checks), the primitive param contracts, and the column schemas.

| Profile | mzPeak spec | Catalog | Reference |
|---|---|---|---|
| `mzpeak-0.9` | 0.9 (commit `d1aaaf84`) | 1.1 | [mzpeak-0.9.md](mzpeak-0.9.md) |

These pages are **generated** from each profile's own bundle, so they cannot drift from
the rules the engine actually runs. Regenerate after changing a profile:

```bash
python docs/gen_profile_page.py mzpeak_validator/profiles/mzpeak-0.9 > docs/profiles/mzpeak-0.9.md
```

See [`docs/gen_profile_page.py`](../gen_profile_page.py) for the generator and
[`docs/validation-design.md`](../validation-design.md) for the overall design.
