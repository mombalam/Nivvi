## Deploy the marketing landing (FastAPI)

The landing page is served by the marketing app (`marketing.py` → `nivvi/marketing_main.py`) and static assets in `web/` mounted at `/static`.

### Health check

- **Path**: `/health`
- **Expected**: `200` with JSON `{"status":"ok","service":"marketing"}`

### Start command (any platform)

Use a host/port that matches your platform conventions:

```bash
uvicorn marketing:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Required runtime

- Python 3.11+

### Environment variables (optional)

If you want to persist waitlist submissions beyond in-memory:

- **`DATABASE_URL`**: e.g. `postgresql+psycopg://user:pass@host:5432/dbname`
- **`NIVVI_STORE_BACKEND=postgres`**
- Run migrations: `alembic upgrade head`

For secure waitlist lead read access:

- **`NIVVI_ADMIN_KEY`**: shared secret required by admin waitlist endpoints

### Routes to verify after deploy

- `/` (landing)
- `/waitlist` (waitlist)
- `/waitlist/success` (success page)
- `/legal/privacy` and `/legal/terms`
- `/robots.txt` and `/sitemap.xml`

### View waitlist submissions

Use an admin key in the `x-admin-key` header.

JSON list:

```bash
curl -H "x-admin-key: $NIVVI_ADMIN_KEY" \
  "https://<your-domain>/v1/admin/waitlist/leads?limit=200"
```

CSV export:

```bash
curl -H "x-admin-key: $NIVVI_ADMIN_KEY" \
  "https://<your-domain>/v1/admin/waitlist/leads.csv" \
  -o nivvi-waitlist-leads.csv
```
