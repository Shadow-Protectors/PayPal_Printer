"""Read-only production preflight. Never print connection strings or secrets."""
import sys
from pathlib import Path


class ConfigurationError(Exception):
    pass


def main():
    try:
        from app.config.settings import settings
        from app.config.database import engine
        from sqlalchemy import text

        required = ('JWT_SECRET_KEY', 'ADMIN_EMAIL', 'SMTP_HOST', 'SMTP_USER',
                    'SMTP_PASSWORD', 'SMTP_FROM_EMAIL', 'RAZORPAY_KEY_ID',
                    'RAZORPAY_KEY_SECRET', 'RAZORPAY_WEBHOOK_SECRET')
        invalid = [key for key in required if not getattr(settings, key, '')
                   or 'REPLACE_' in str(getattr(settings, key, ''))]
        if invalid:
            raise ConfigurationError('Configure: ' + ', '.join(invalid))
        if settings.ENVIRONMENT != 'production' or engine.dialect.name != 'mysql':
            raise ConfigurationError('This deployment requires production mode and MySQL.')
        if any(not origin.startswith('https://') for origin in settings.ALLOWED_ORIGINS):
            raise ConfigurationError('Production origins must use HTTPS.')
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
        import tempfile
        with tempfile.TemporaryFile(dir=Path(settings.STORAGE_ROOT)) as file:
            file.write(b'preflight')
        print('Configuration, database connection, and storage access passed.')
        print('SMTP delivery, payments, Apache routing and physical printing still need live checks.')
        return 0
    except ConfigurationError as exc:
        print(str(exc), file=sys.stderr)
    except Exception as exc:
        print(f'Preflight failed ({type(exc).__name__}). Check private configuration, MySQL and storage permissions.', file=sys.stderr)
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
