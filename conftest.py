"""
Root conftest.py — stubs out heavy optional dependencies so tests can run
without PyMuPDF (fitz), pyproj, requests, etc. being installed in the dev env.
"""
import sys
import types


def _make_stub(name):
    mod = types.ModuleType(name)
    mod.__spec__ = None
    return mod


# ---- fitz (PyMuPDF) --------------------------------------------------------
if "fitz" not in sys.modules:
    fitz_stub = _make_stub("fitz")

    class _FitzDoc:
        def __init__(self, *a, **kw):
            pass
        def __iter__(self):
            return iter([])
        def __len__(self):
            return 0
        def close(self):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    fitz_stub.open = lambda *a, **kw: _FitzDoc()
    sys.modules["fitz"] = fitz_stub

# ---- pyproj ----------------------------------------------------------------
if "pyproj" not in sys.modules:
    pyproj_stub = _make_stub("pyproj")

    class _Transformer:
        @staticmethod
        def from_crs(*a, **kw):
            return _Transformer()
        def transform(self, x, y):
            return x, y

    pyproj_stub.Transformer = _Transformer
    sys.modules["pyproj"] = pyproj_stub

# ---- pdfplumber ------------------------------------------------------------
if "pdfplumber" not in sys.modules:
    pdfplumber_stub = _make_stub("pdfplumber")

    class _PDFPlumberDoc:
        pages = []
        def __enter__(self):
            return self
        def __exit__(self, *a):
            pass

    pdfplumber_stub.open = lambda *a, **kw: _PDFPlumberDoc()
    sys.modules["pdfplumber"] = pdfplumber_stub

# ---- requests --------------------------------------------------------------
if "requests" not in sys.modules:
    requests_stub = _make_stub("requests")
    requests_stub.get = lambda *a, **kw: None
    sys.modules["requests"] = requests_stub
