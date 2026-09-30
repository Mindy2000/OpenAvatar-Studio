"""Keep module-level application initialization away from users' runtime data."""
import os
import tempfile


_session_data = tempfile.TemporaryDirectory(prefix="openavatar-pytest-")
os.environ["OPENAVATAR_DATA_DIR"] = _session_data.name
