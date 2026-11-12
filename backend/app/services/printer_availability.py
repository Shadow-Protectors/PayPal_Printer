"""One availability policy for admin, checkout and release."""
from datetime import datetime, timezone, timedelta
from app.config.settings import settings


def recent(value):
    if value is None:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value >= datetime.now(timezone.utc) - timedelta(seconds=settings.HEARTBEAT_TIMEOUT_SECONDS)


def printer_state(printer, server):
    if settings.ENVIRONMENT.lower() in ("production", "prod"):
        if not server or not server.is_enabled or str(getattr(server.status, 'value', server.status)) != 'ONLINE' or not recent(server.last_heartbeat):
            return 'OFFLINE'
        if not printer.is_enabled:
            return 'DISABLED'
        if printer.has_mismatch or not recent(printer.last_seen):
            return 'OFFLINE'
        return printer.printer_status or 'UNKNOWN'
    else:
        if not server or not server.is_enabled:
            return 'OFFLINE'
        if not printer or not printer.is_enabled:
            return 'DISABLED'
        return printer.printer_status or 'READY'


def available(printer, server):
    if settings.ENVIRONMENT.lower() in ("production", "prod"):
        return printer.is_active and printer_state(printer, server) in ('READY', 'BUSY')
    return bool(printer and printer.is_active and printer.is_enabled)


def order_problem(db, order, job):
    from app.db.models.printer import Printer
    from app.db.models.print_server import PrintServer
    if order.status.value not in ('WAITING_FOR_OTP', 'RELEASED', 'PRINTING'):
        return (job.error_code, job.error_message) if job else (None, None)
    server = db.get(PrintServer, order.print_server_id)
    if not server or not recent(server.last_heartbeat) or not server.is_enabled:
        return 'STATION_OFFLINE', 'Print station offline. Waiting for it to reconnect.'
    printer = db.get(Printer, job.printer_id) if job and job.printer_id else None
    if not printer:
        name = (order.print_settings or {}).get('cups_printer_name')
        printer = db.query(Printer).filter_by(server_id=order.print_server_id, cups_printer_name=name).first() if name else None
    if printer:
        state = printer_state(printer, server)
        if state not in ('READY', 'BUSY'):
            return 'PRINTER_' + state, {
                'OFFLINE': 'Printer offline. Waiting for it to reconnect.',
                'OUT_OF_PAPER': 'Load paper to continue printing.',
                'STOPPED': 'Printer paused. Ask the attendant to resume it.',
            }.get(state, 'Printer unavailable. Ask the attendant for help.')
    return (job.error_code, job.error_message) if job else (None, None)
