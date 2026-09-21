"""Routing regression: isolated storage, no startup jobs or external services."""
import os
import tempfile
from pathlib import Path

_data = tempfile.TemporaryDirectory(prefix='miell_portal_test_')
os.environ['MIELL_DATA_DIR'] = _data.name
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(_data.name) / 'attendance.db').as_posix()
os.environ['JWT_SECRET'] = 'portal-routing-test-only'

from fastapi.testclient import TestClient
import main


def test_portal_and_attendance_routes():
    client = TestClient(main.app)
    for path in ['/', '/?view=attendance', '/?view=overview']:
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers['content-type'].startswith('text/html')
        assert 'id="loginPanel"' in response.text
        assert '/portal.js' in response.text
    assert client.get('/admin').headers['content-type'].startswith('text/html')
    script = client.get('/portal.js')
    assert script.status_code == 200
    assert "location.replace('/admin')" in script.text
    assert client.get('/api/me').status_code == 401
