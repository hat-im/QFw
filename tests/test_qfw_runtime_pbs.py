import json
import socket
import subprocess
import sys
import types
from pathlib import Path

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "setup"))
sys.path.insert(0, str(_REPO_ROOT / "services"))
sys.path.insert(0, str(_REPO_ROOT / "DEFw" / "python" / "infra"))

try:
    import cdefw_global  # noqa: F401
except ImportError:
    _cdefw_global = types.ModuleType("cdefw_global")
    _cdefw_global.get_node_name = lambda: "qfw-test"
    sys.modules["cdefw_global"] = _cdefw_global

from qfw_runtime import _process_launcher
from qfw_runtime import commands
from qfw_runtime import config as qfw_config
from qfw_runtime import service_plane
from tests.test_qfw_service_plane import write_runtime_configuration
from tests.test_qfw_service_plane import write_site_configuration


THIS_NODE = "x4102c5s2b0n0"
OTHER_NODE = "x4102c5s3b0n0"
DOMAIN = ".hostmgmt2102.cm.aurora.alcf.anl.gov"
ALLOCATION_CONTEXTS = (
    service_plane._allocation_context,
    lambda: commands._allocation_context_from_env(),
    lambda: _process_launcher._allocation_context_from_env(),
)


@pytest.fixture
def pbs_job(tmp_path, monkeypatch):
    for name in list(qfw_config.os.environ):
        if name.startswith(("SLURM_", "QFW_GROUP", "QFW_ALLOCATION_MODE")):
            monkeypatch.delenv(name)
    monkeypatch.setattr(socket, "gethostname", lambda: THIS_NODE)

    def job(*nodefile_lines):
        nodefile = tmp_path / "pbs-nodefile"
        nodefile.write_text(
            "".join(f"{line}\n" for line in nodefile_lines), encoding="utf-8")
        monkeypatch.setenv("PBS_NODEFILE", str(nodefile))
        monkeypatch.setenv("PBS_JOBID", "8123.aurora-pbs-0001")
    return job


@pytest.mark.parametrize("allocation_context", ALLOCATION_CONTEXTS)
def test_a_one_node_pbs_job_is_a_pbs_allocation_of_this_node(
        pbs_job, allocation_context):
    pbs_job(*[THIS_NODE + DOMAIN] * 4)

    allocation = allocation_context()

    assert allocation["mode"] == "pbs"
    assert allocation["group0"] == [THIS_NODE + DOMAIN]
    assert allocation["group1"] == [THIS_NODE + DOMAIN]


@pytest.mark.parametrize("allocation_context", ALLOCATION_CONTEXTS)
def test_a_pbs_allocation_puts_this_node_first_once(
        pbs_job, allocation_context):
    pbs_job(OTHER_NODE + DOMAIN, OTHER_NODE + DOMAIN, THIS_NODE + DOMAIN)

    allocation = allocation_context()

    assert allocation["group1"] == [THIS_NODE + DOMAIN, OTHER_NODE + DOMAIN]


@pytest.mark.parametrize("allocation_context", ALLOCATION_CONTEXTS)
def test_a_slurm_allocation_inside_a_pbs_environment_stays_slurm(
        pbs_job, monkeypatch, allocation_context):
    pbs_job(THIS_NODE)
    monkeypatch.setenv("SLURM_JOB_NODELIST", "c1")

    assert allocation_context()["mode"] == "slurm"


def test_a_pbs_allocation_needs_this_node_in_the_nodefile(pbs_job):
    pbs_job(OTHER_NODE + DOMAIN)

    with pytest.raises(ValueError, match="PBS_NODEFILE"):
        qfw_config.pbs_nodelist()


def test_a_pbs_node_launch_runs_the_command_here(pbs_job):
    pbs_job(THIS_NODE)
    command = ["prte", "--daemonize"]

    assert service_plane._node_launch(
        THIS_NODE, command, service_plane._allocation_context()) == command
    assert commands._application_launch_command(
        ["app"], commands._allocation_context_from_env(),
        {"nodes": 1, "ntasks": 1}) == ["app"]


def test_a_pbs_manager_will_not_place_a_role_on_another_node(
        tmp_path, pbs_job):
    pbs_job(THIS_NODE, OTHER_NODE)
    site, _manifest = write_site_configuration(tmp_path, [])
    runtime = write_runtime_configuration(tmp_path, prte=False)
    parser = service_plane._role_argument_parser("qfw-dir-svc", "directory")
    args = parser.parse_args([
        "start", "--run-dir", str(tmp_path / "run"),
        "--site-config", str(site), "--runtime-config", str(runtime),
        "--node", OTHER_NODE, "--dry-run",
    ])

    with pytest.raises(service_plane.ServicePlaneError, match=OTHER_NODE):
        service_plane.start(args)


def test_a_pbs_dvm_spans_every_node_of_the_job(tmp_path, pbs_job, monkeypatch):
    pbs_job(THIS_NODE + DOMAIN, OTHER_NODE + DOMAIN)
    allocation = service_plane._allocation_context()
    uri_path = tmp_path / "prte_dvm" / "dvm-uri"
    state = {
        "run_dir": str(tmp_path),
        "owner": "application",
        "dry_run": False,
        "dvm": {
            "launch_node": allocation["group1"][0],
            "nodes": allocation["group1"],
            "uri_path": str(uri_path),
        },
        "allocation": allocation,
        "components": {},
    }
    launches = []

    def run_here(launch):
        launches.append(list(launch))
        uri_path.write_text("dvm-uri\n", encoding="utf-8")
        Path(launch[launch.index("--report-pid") + 1]).write_text(
            "7201\n", encoding="utf-8")
        return subprocess.CompletedProcess(launch, 0)

    monkeypatch.setattr(
        service_plane.subprocess, "run", lambda launch, env: run_here(launch))
    monkeypatch.setattr(
        service_plane, "_read_process_identity",
        lambda pid, *_args: {"pid": pid})
    monkeypatch.setattr(
        service_plane, "_command_path", lambda name, env=None: name)
    monkeypatch.setattr(service_plane.os, "geteuid", lambda: 1000)
    monkeypatch.delenv("QFW_JOB_ID", raising=False)

    service_plane._start_prte(state, timeout=1)

    assert launches == [[
        "prte", "--host",
        f"{THIS_NODE + DOMAIN}:*,{OTHER_NODE + DOMAIN}:*",
        "--report-uri", str(uri_path),
        "--report-pid", str(uri_path.with_name("pid")),
        "--keepalive", "0", "--daemonize",
    ]]


def test_a_pbs_run_is_prepared_in_its_pbs_job(tmp_path, pbs_job):
    pbs_job(THIS_NODE)
    site = {
        "install": {
            "qfw-prefix": str(tmp_path / "qfw"),
            "defw-prefix": str(tmp_path / "defw"),
        },
        "directory-service": {
            "name": "qfw-site-dirsvc",
            "endpoint": "pbs-head:8090",
        },
    }

    state = qfw_config.prepare_run_state(
        tmp_path / "site.yaml", tmp_path / "runtime.yaml", site, {},
        run_id="job-run", run_dir=tmp_path / "run", dry_run=True)

    assert state["pbs_job_id"] == "8123.aurora-pbs-0001"


def _run_of(base, name, pbs_job_id):
    state_dir = base / name / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "runtime-state.json").write_text(json.dumps({
        "run_dir": str(base / name), "pbs_job_id": pbs_job_id,
    }), encoding="utf-8")
    return (base / name).resolve()


@pytest.mark.parametrize("inherited_job, uses_inherited", [
    ("8123.aurora-pbs-0001", True),
    ("7000.aurora-pbs-0001", False),
])
def test_run_discovery_keeps_to_the_runs_of_this_pbs_job(
        tmp_path, pbs_job, monkeypatch, capsys, inherited_job,
        uses_inherited):
    pbs_job(THIS_NODE)
    base = tmp_path / "runs"
    inherited = _run_of(base, "inherited", inherited_job)
    own = _run_of(base, "own", "8123.aurora-pbs-0001")
    (base / "current").write_text("own\n", encoding="utf-8")
    monkeypatch.setenv("QFW_RUN_BASE_DIR", str(base))
    monkeypatch.setenv("QFW_RUN_TMP_PATH", str(inherited))

    found = qfw_config.current_run_dir().resolve()

    assert found == (inherited if uses_inherited else own)
    if not uses_inherited:
        assert f"PBS job {inherited_job}" in capsys.readouterr().err
