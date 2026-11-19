# IBM's backend records, read with an IBM QDMI session's settings from a
# loopback IAM and Runtime API.

import json
import pathlib
import sys
import threading
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

pytest.importorskip("qiskit_ibm_runtime")
jwt = pytest.importorskip("jwt")

SERVICES = pathlib.Path(__file__).resolve().parents[2] / "services"

CONFIGURATION = {
	"backend_name": "ibm_fez", "n_qubits": 3, "basis_gates": ["cz", "rz", "sx", "x"],
	"coupling_map": [[0, 1], [1, 2]], "max_shots": 100000}
PROPERTIES = {"qubits": [], "gates": [], "last_update_date": "2026-01-01T00:00:00Z"}
EXPIRY = 4102444800
IAM_TOKEN = jwt.encode({"iat": EXPIRY - 3600, "exp": EXPIRY}, "s" * 32, algorithm="HS256")


@pytest.fixture
def backend_records(monkeypatch):
	# Load the module without starting QPM services or importing DEFw.
	for name, path in (
			("svc_lib_qpm", SERVICES / "svc_lib_qpm"),
			("svc_lib_qpm.drivers", SERVICES / "svc_lib_qpm/drivers")):
		if name not in sys.modules:
			package = types.ModuleType(name)
			package.__path__ = [str(path)]
			monkeypatch.setitem(sys.modules, name, package)
	from svc_lib_qpm.drivers.ibm_runtime import backend_records
	return backend_records


@pytest.fixture
def ibm():
	seen = []

	class Handler(BaseHTTPRequestHandler):
		def log_message(self, format, *args):
			pass

		def reply(self, body):
			content = json.dumps(body).encode()
			self.send_response(200)
			self.send_header("Content-Type", "application/json")
			self.send_header("Content-Length", str(len(content)))
			self.end_headers()
			self.wfile.write(content)

		def do_POST(self):
			self.rfile.read(int(self.headers["Content-Length"]))
			seen.append(("POST", self.path, None, None))
			self.reply({
				"access_token": IAM_TOKEN, "refresh_token": "refresh",
				"token_type": "Bearer", "expires_in": 3600,
				"expiration": EXPIRY})

		def do_GET(self):
			seen.append(("GET", self.path.split("?")[0],
				self.headers["Authorization"], self.headers["Service-CRN"]))
			records = {
				"/api/v1/backends/ibm_fez/configuration": CONFIGURATION,
				"/api/v1/backends/ibm_fez/properties": PROPERTIES}
			self.reply(records[self.path.split("?")[0]])

	server = HTTPServer(("127.0.0.1", 0), Handler)
	threading.Thread(target=server.serve_forever, daemon=True).start()
	yield f"http://127.0.0.1:{server.server_port}", seen
	server.shutdown()
	server.server_close()


def test_records_come_from_the_sessions_api_with_its_iam_token(backend_records, ibm):
	url, seen = ibm
	access = {
		"base_url": url + "/api", "api_key": "key", "backend_name": "ibm_fez",
		"instance_crn": "crn:v1:bluemix:public:quantum-computing:us-east:a/x:y::",
		"auth_url": url + "/identity/token"}

	configuration, properties = backend_records(access)

	assert configuration == CONFIGURATION
	assert properties == dict(PROPERTIES, backend_name="ibm_fez")
	assert seen == [
		("POST", "/identity/token", None, None),
		("GET", "/api/v1/backends/ibm_fez/configuration",
			f"Bearer {IAM_TOKEN}", access["instance_crn"]),
		("GET", "/api/v1/backends/ibm_fez/properties",
			f"Bearer {IAM_TOKEN}", access["instance_crn"])]
