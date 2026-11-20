# deadlock-api match metadata

`match_140328807_metadata.json.gz` is the full response of deadlock-api's
`GET /v1/matches/140328807/metadata` for Deadlock match 140328807 (a 35-minute custom match, the
Archmother winning), re-serialised without whitespace and gzipped. It's a real match: the
account IDs are the players' Steam account IDs as deadlock-api publishes them.

It was fetched for the postgame design work (`design/dayshift/postgame/`, cached under
`out/140328807/api/metadata.json`) and copied here unchanged, so the postgame tests
(`tests/test_postgame.py`, `tests/test_share_card.py`) run on real data without calling
deadlock-api.

To refresh it, fetch the same URL again and run:

```bash
uv run python -c "import gzip, json, sys; d = json.load(open(sys.argv[1], encoding='utf-8')); \
open(sys.argv[2], 'wb').write(gzip.compress(json.dumps(d, separators=(',', ':')).encode(), 9, mtime=0))" \
metadata.json tests/fixtures/deadlock/match_140328807_metadata.json.gz
```
