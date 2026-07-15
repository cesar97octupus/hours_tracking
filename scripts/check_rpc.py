"""Standalone RPC sanity check against a real Odoo 18 server.

Run this before wiring up any UI to confirm: authentication works, the
logged-in user resolves to an employee, task/ticket fetching works, and to
discover the real shape of the custom `type_analytic_line_id` field (which
isn't present in any addon source available on this machine and must be
probed live).

Usage:
    venv\\Scripts\\python scripts\\check_rpc.py

Reads ODOO_URL / ODOO_DB / ODOO_USERNAME / ODOO_PASSWORD from the
environment if set, otherwise prompts interactively (password via getpass,
never echoed or logged).
"""
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.exceptions import OdooError
from app.odoo_client import OdooClient


def prompt(env_var: str, label: str, secret: bool = False) -> str:
    value = os.environ.get(env_var)
    if value:
        return value
    return getpass.getpass(f"{label}: ") if secret else input(f"{label}: ")


def main() -> int:
    url = prompt("ODOO_URL", "Odoo URL (e.g. https://my-odoo.example.com)")
    db = prompt("ODOO_DB", "Database name")
    username = prompt("ODOO_USERNAME", "Username")
    password = prompt("ODOO_PASSWORD", "Password", secret=True)

    client = OdooClient(url, db, username, password)

    try:
        uid = client.authenticate()
        print(f"[OK] Authenticated. uid={uid}")

        ctx = client.get_user_context()
        print(f"[OK] User context: login={ctx['login']!r} email={ctx.get('email')!r} name={ctx['name']!r}")

        employee = client.resolve_employee(ctx.get("email"))
        print(f"[OK] Employee resolved: id={employee.employee_id} name={employee.name!r} work_email={employee.work_email!r}")

        tasks = client.fetch_my_tasks()
        print(f"[OK] {len(tasks)} task(s) found. First 5:")
        for t in tasks[:5]:
            print(f"       - #{t.id} {t.name!r} (project: {t.project_name!r})")

        helpdesk_installed = client.probe_helpdesk_installed()
        print(f"[OK] helpdesk_timesheet installed: {helpdesk_installed}")

        if helpdesk_installed:
            tickets = client.fetch_my_tickets()
            print(f"[OK] {len(tickets)} ticket(s) found. First 5:")
            for t in tickets[:5]:
                print(f"       - #{t.id} {t.name!r} (project: {t.project_name!r})")

        capability = client.probe_type_analytic_line_field()
        if not capability.present:
            print("[INFO] type_analytic_line_id: NOT present on account.analytic.line on this server.")
        else:
            print(
                f"[OK] type_analytic_line_id: type={capability.ttype!r} "
                f"comodel={capability.comodel!r} required={capability.required} "
                f"selection={capability.selection!r}"
            )
            if capability.ttype == "many2one" and capability.comodel:
                options = client.fetch_type_analytic_line_options(capability.comodel)
                print(f"[OK] {len(options)} option(s) for {capability.comodel}. First 5:")
                for o in options[:5]:
                    print(f"       - #{o.id} {o.name!r}")

        print("\nAll checks completed successfully.")
        return 0
    except OdooError as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
