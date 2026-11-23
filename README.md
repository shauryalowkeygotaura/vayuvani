# VayuVani (वायुवाणी)

Delhi air, and who is dirtying it. Every hour it reads all 54 CPCB/DPCC stations, wind and satellite fires, and guesses the cause of each PM2.5 spike. It only names a source when it is 95% sure. Otherwise it says "unsure".

Live map: https://shauryalowkeygotaura.github.io/vayuvani/

How it works and where it fails: [docs/KAUN.md](docs/KAUN.md). Near IIT Delhi it is right about 97% of the time on held-out data. Farther out it is not proven yet.

```bash
pip install -r requirements-engine.txt
python -m pytest
python -m attribution.run demo        # offline, fake data
doppler run -- python -m attribution.run hourly
```

Hourly runs, agency digests and approvals are GitHub Actions in `.github/workflows/`. Database setup: run `supabase/migrations/*.sql` in order.
