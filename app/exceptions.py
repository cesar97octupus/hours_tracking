class OdooError(Exception):
    """Base class for all errors raised by the Odoo RPC layer."""


class OdooConnectionError(OdooError):
    """Network/DNS/timeout/TLS failure talking to the Odoo server."""


class OdooAuthError(OdooError):
    """Odoo rejected the supplied credentials."""


class OdooFault(OdooError):
    """Any other server-side xmlrpc.client.Fault (validation, access rights, etc.)."""


class EmployeeNotFoundError(OdooError):
    """No hr.employee.public record matched the logged-in user."""


class MultipleEmployeesFoundError(OdooError):
    """More than one hr.employee.public record matched the logged-in user."""


class LocalValidationError(Exception):
    """A local, pre-RPC validation failure (e.g. missing required field)."""


class DuplicateFoundError(Exception):
    """A likely-duplicate account.analytic.line already exists in Odoo.

    Not a failure — a flow-control signal the UI catches to ask the user
    whether to proceed anyway (retry with confirm_duplicate=True) or cancel."""

    def __init__(self, existing_odoo_id: int):
        self.existing_odoo_id = existing_odoo_id
        super().__init__(f"Possible duplicate: Odoo record #{existing_odoo_id}")
