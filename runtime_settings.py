"""Local defaults shared by the Windows launcher and server deployment."""
import os
import secrets
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.getenv('MIELL_DATA_DIR', str(BASE_DIR / 'data'))).resolve()
DATA_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('DATABASE_URL', 'sqlite:///' + (DATA_DIR / 'attendance.db').as_posix())
if os.environ['DATABASE_URL'].startswith('postgres://'):
    os.environ['DATABASE_URL'] = os.environ['DATABASE_URL'].replace('postgres://', 'postgresql://', 1)
if os.getenv('RENDER') and not os.environ['DATABASE_URL'].startswith(('postgresql:', 'postgresql+psycopg2:')):
    raise RuntimeError('Render vyžaduje externú PostgreSQL databázu v DATABASE_URL, aby sa údaje nestratili.')
if not os.getenv('JWT_SECRET'):
    if os.getenv('RENDER'):
        raise RuntimeError('Na Renderi nastav stabilný JWT_SECRET.')
    secret_path = DATA_DIR / '.session-secret'
    try:
        with secret_path.open('x', encoding='utf-8') as f:
            f.write(secrets.token_urlsafe(48))
    except FileExistsError:
        pass
    os.environ['JWT_SECRET'] = secret_path.read_text(encoding='utf-8').strip()


def verify_password(password, stored, context):
    if stored.startswith('miell_pbkdf2$'):
        from quality.legacy import verify_password as verify_legacy
        _, salt, digest = stored.split('$', 2)
        return verify_legacy(password, salt, digest)
    return context.verify(password, stored)
