# Demo 01 - Basic FHIR R4 validation

This demo validates a small FHIR `Bundle` (`bundle.json`) that contains two
entries: a `Patient` and an `Observation`. The file deliberately includes
several common authoring mistakes so you can see FHIRLINT catch real problems
with line-level reporting.

## What's wrong in `bundle.json`

1. **Patient.gender** is `"M"` — not a valid `administrative-gender` code
   (must be `male` / `female` / `other` / `unknown`).
2. **Patient.birthDate** is `"1985-13-02"` — month `13` is not a valid FHIR
   `date`.
3. **Patient.id** is `"pat 1"` — contains a space, violating the FHIR id
   pattern `[A-Za-z0-9-.]{1,64}`.
4. **Observation.status** is `"done"` — not in the required observation-status
   value set (`final`, `preliminary`, ...).
5. **Observation** is missing its required `code` element.

## Run it

```bash
# human-readable table
python -m fhirlint validate demos/01-basic/bundle.json

# machine-readable JSON (for CI / piping)
python -m fhirlint validate demos/01-basic/bundle.json --format json
```

## Expected result

FHIRLINT reports **5 error-severity findings** (the five issues above), each
with a source line number and a JSON-pointer-style path such as
`Bundle.entry[0].resource.gender`. The process exits with code **1**, so it
fails a CI gate.

A clean file (fix all five issues) would print `no issues found` and exit `0`.
