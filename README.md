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

## TODOs

La pestaña **TODO** guarda los pendientes del día (categoría, prioridad, subtareas,
vínculo opcional a tarea/ticket de Odoo y cronómetro directo desde el TODO). Cada cambio
regenera `todos/current.md`, que un hook `SessionStart` de Claude Code
(`scripts/claude_todos_context.py`, registrado en `~/.claude/settings.json`) inyecta
al inicio de cada sesión.

### Pendiente de desarrollar

- [ ] **Gestión de categorías**: renombrar, cambiar color y eliminar categorías (hoy solo se crean desde el asistente).
- [ ] **Recurrencia**: TODOs repetitivos (diarios, semanales…).
- [ ] **Mejoras visuales** de la pestaña TODO (anchos, tema oscuro, botones).
