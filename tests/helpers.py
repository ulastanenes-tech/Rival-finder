import io
import os
import pathlib
import tempfile
import urllib.error

from playscout import db

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class _Resp(io.BytesIO):
    def __init__(self, body, status=200):
        super().__init__(body.encode("utf-8"))
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeOpener:
    """Ağ yerine kullanılan sahte açıcı. routes: URL-öneki -> gövde veya Exception."""

    def __init__(self, routes):
        self.routes = routes
        self.requested = []

    def open(self, req, timeout=None):
        url = req.full_url
        self.requested.append(url)
        for prefix, value in self.routes.items():
            if url.startswith(prefix):
                if isinstance(value, Exception):
                    raise value
                return _Resp(value)
        raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)


def temp_conn():
    d = tempfile.mkdtemp()
    return db.connect(os.path.join(d, "test.db"))


def no_sleep(_s):
    return None
