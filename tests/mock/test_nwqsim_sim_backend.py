import pathlib
import types

import yaml

import svc_nwqsim_qpm.svc_qrc as svc_qrc
from svc_nwqsim_qpm.svc_qrc import QRC
from util.mpi import backend_config


SERVICES_DIR = (
	pathlib.Path(__file__).resolve().parents[2]
	/ "share" / "qfw" / "config" / "services")


def _form_cmd(monkeypatch, tmp_path, launch_config, **info):
	service_config = tmp_path / "services.yaml"
	service_config.write_text("{}\n")
	monkeypatch.setenv("QFW_SERVICE_CONFIG", str(service_config))
	monkeypatch.setattr(svc_qrc, "backend_config", lambda name: launch_config)
	monkeypatch.setattr(svc_qrc, "backend_wrapper", lambda name: None)
	monkeypatch.setattr(
		"shutil.which", lambda name: "/usr/bin/circuit_runner.nwqsim")
	monkeypatch.delenv("QFW_DVM_URI_PATH", raising=False)
	circ = types.SimpleNamespace(info={
		"qfw_backend": "circuit_runner.nwqsim", "np": 1, **info})
	return QRC(start=False).form_cmd(circ, "/tmp/circuit.qasm")


def _backend_argument(command):
	words = command.split()
	return words[words.index("-backend") + 1]


def test_backend_defaults_to_openmp(monkeypatch, tmp_path):
	command = _form_cmd(monkeypatch, tmp_path, {})

	assert _backend_argument(command) == "OPENMP"


def test_empty_sim_backend_defaults_to_openmp(monkeypatch, tmp_path):
	command = _form_cmd(monkeypatch, tmp_path, {"sim-backend": ""})

	assert _backend_argument(command) == "OPENMP"


def test_sim_backend_setting_selects_the_backend(monkeypatch, tmp_path):
	command = _form_cmd(monkeypatch, tmp_path, {"sim-backend": "NVGPU"})

	assert _backend_argument(command) == "NVGPU"


def test_job_backend_overrides_the_sim_backend_setting(monkeypatch, tmp_path):
	command = _form_cmd(monkeypatch, tmp_path, {"sim-backend": "NVGPU"}, backend="MPI")

	assert _backend_argument(command) == "MPI"


def _load_profile(profile):
	runtime = yaml.safe_load(
		(SERVICES_DIR.parent / "runtime" / f"{profile}.yaml").read_text())
	manifest = pathlib.Path(
		runtime["local-services"]["service-manifest"].replace(
			"${QFW_PREFIX}", str(SERVICES_DIR.parents[3])))
	return manifest, yaml.safe_load(manifest.read_text())


def test_local_profile_leaves_the_backend_unset():
	manifest, config = _load_profile("local")

	assert manifest.name == "local-services.yaml"
	assert "sim-backend" not in backend_config("nwqsim", config)


def test_local_gpu_profile_selects_nvgpu():
	manifest, config = _load_profile("local-gpu")

	assert manifest.name == "local-gpu-services.yaml"
	assert backend_config("nwqsim", config)["sim-backend"] == "NVGPU"


def test_local_gpu_manifest_differs_from_local_only_by_sim_backend():
	_, local = _load_profile("local")
	_, gpu = _load_profile("local-gpu")

	for service in gpu["services"]:
		if service["name"] == "nwqsim":
			del service["provider-launch"]["sim-backend"]
	assert gpu == local
