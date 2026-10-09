# Audora voice test

A short blind listening test. Each listener hears three lines, one per character, each read by three different voices in a shuffled order, and answers two questions per line. At the end they get a short result code to send back on WhatsApp.

The page never names the voices. The mapping from clip id to voice lives in `key.json`, which is generated locally and never committed.

## Rebuild the clips

```sh
python3 build.py                           # reads the renders from ../pipeline-dispatcher
python3 build.py --whatsapp 91XXXXXXXXXX   # prefill the Send on WhatsApp button with your number
```

Writes `clips/*.m4a`, `trials.json` (public) and `key.json` (local only).

## Test locally

```sh
python3 -m http.server 8010
open http://localhost:8010/
```

## Publish

The repo is served from the `main` branch root on GitHub Pages. Commit and push; the page updates within a minute.

## Tally the results

Paste every WhatsApp message that contains a code into `codes.txt` (whole chat text is fine), then:

```sh
python3 tally.py
```

Prints the table and writes `results.md`. Add `--json` for raw counts.
