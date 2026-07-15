# hours_tracking

Desktop timesheet app: connects to an Odoo 18 server, lets you pick an assigned
task or helpdesk ticket, run a stopwatch, and export the tracked time as a
timesheet entry (`account.analytic.line`).

## Setup

```
python -m venv venv
venv\Scripts\python -m pip install -r requirements.txt
```

## Run

```
venv\Scripts\python run.py
```

## Standalone RPC check

Before running the full app against a new server, sanity-check the connection
and discover the server's `type_analytic_line_id` field shape:

```
venv\Scripts\python scripts\check_rpc.py
```
