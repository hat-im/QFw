# IBM's own records for a backend, read through qiskit-ibm-runtime's REST
# client with the settings an IBM QDMI session opens with.

from defw_exception import DEFwExecutionError
from ibm_cloud_sdk_core import IAMTokenManager
from qiskit_ibm_runtime.api.client import RuntimeClient
from qiskit_ibm_runtime.api.client_parameters import ClientParameters


class SessionParameters(ClientParameters):
	def __init__(self, access):
		super().__init__(
			channel="ibm_cloud", token=access["api_key"],
			url=access["base_url"] + "/v1", instance=access["instance_crn"],
			url_resolver=lambda url, *_: url)
		self.auth_url = access.get("auth_url")

	def get_auth_handler(self):
		auth = super().get_auth_handler()
		if self.auth_url:
			auth.tm = IAMTokenManager(self.token, url=self.auth_url)
		return auth


def backend_records(access):
	client = RuntimeClient(SessionParameters(access))
	name = access["backend_name"]
	configuration = client.backend_configuration(name)
	if not configuration:
		raise DEFwExecutionError(
			f"IBM returned no configuration for backend {name!r}")
	return configuration, client.backend_properties(name)
