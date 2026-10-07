# Tax Declaration XML API (FastAPI + PostgreSQL)

A backend for self-employed people. They record income and expenses, the API calculates a yearly
tax declaration, generates it as XML, checks it against an XSD schema, and only lets it be
submitted after the user approves it. Every step is written to an audit log.

Built with **Python 3.12, FastAPI, SQLAlchemy 2, PostgreSQL, lxml (XML + XSD), pytest, Docker**.

> The tax rules and the XML schema are simplified and only for illustration. They are not any
> country's real tax law or official filing format. Both are kept in config and one XSD file
> so they can be replaced with the real ones.

## Screenshots

| API docs (Swagger) | Generated XML |
|---|---|
| ![Swagger docs](docs/screenshots/swagger-docs.png) | ![Declaration XML](docs/screenshots/declaration-xml.png) |

| Audit log | Test run |
|---|---|
| ![Audit log](docs/screenshots/audit-log.png) | ![Tests](docs/screenshots/test-run.png) |

## What it does

| Step | Endpoint |
|---|---|
| Create a taxpayer (tax ID and optional data-box ID) | `POST /taxpayers` |
| Record income or an expense | `POST /taxpayers/{id}/entries` |
| Preview the year's totals | `GET /taxpayers/{id}/summary?year=2025&expense_method=flat_rate` |
| Generate or regenerate the declaration (draft) | `POST /taxpayers/{id}/declarations` |
| Download the XML | `GET /declarations/{id}/xml` |
| Approve it (user sign-off) | `POST /declarations/{id}/approve` |
| Submit it and store the receipt | `POST /declarations/{id}/submit` |
| See the history | `GET /declarations/{id}/audit` |
| Check any XML against the schema | `POST /xml/validate` |

Interactive docs are at `/docs` once it is running.

## Design decisions

- **Money is stored in integer cents**, never floats. Rounding is explicit (`ROUND_HALF_UP`), and
  the tax base is rounded down to whole units.
- **The XML is validated against the XSD before it is saved.** If the schema rejects it, the API
  returns every error with its line number and nothing is stored.
- **One declaration per taxpayer per year**, enforced by a unique constraint. A draft can be
  regenerated as often as needed. Once it is approved or submitted, that year is locked: new
  entries and regeneration are refused with `409`.
- **Approval is tied to the exact XML.** Its SHA-256 hash is stored, and submission is refused if
  the XML changed after approval.
- **Submission is idempotent.** Calling submit twice returns the stored receipt instead of
  filing twice.
- **The submission channel can be swapped.** Endpoints depend on a `SubmissionGateway`
  interface. The default `SandboxGateway` never contacts an outside system. A real channel (for
  example a SOAP data-box client) can be plugged in without changing the endpoints.
- **Audit trail:** generated, regenerated, approved, submitted and rejected events are logged
  with the XML hash and receipt ID.

## Run it

```bash
docker compose up --build
# API on http://localhost:8000, docs on http://localhost:8000/docs
```

Without Docker:

```bash
pip install -r requirements.txt
export APP_DATABASE_URL=postgresql+psycopg2://tax:tax@localhost:5432/tax
uvicorn app.main:app --reload
```

## Tests

```bash
pytest -q
```

The 11 tests run on an in-memory SQLite database. They cover the tax calculation (actual vs
flat-rate expenses, the cap, losses, the credit limit) and the whole API flow: validation,
duplicate tax IDs, generate → approve → submit, idempotent submission, locking a year after
approval, a rejected submission, and the XML validation endpoint. GitHub Actions runs them on
every push.

## Possible next steps

- Alembic migrations instead of creating tables at start-up
- Authentication, so each user only sees their own records
- A real gateway client with retries and a signed request
- A React front end for entering records and reviewing the XML before approving it
