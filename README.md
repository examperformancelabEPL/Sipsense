# SipSense

Water supply business management app (customers, delivery ledger, billing,
outstanding balances, P&L) with a shared Postgres backend so the same data
is live on every device.

## Deploy
1. Push this repo to GitHub.
2. In Render: New Postgres database, then New Web Service pointing at this repo
   - Build command: `pip install -r requirements.txt`
   - Start command: `gunicorn app:app`
   - Environment variable: `DATABASE_URL` = the Postgres internal connection string
