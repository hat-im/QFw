# Build Optional Simulator Dependencies

QFw does not build NWQSim or TNQVM during its primary CMake installation.
Administrators build the simulators independently, publish their runtime
environments as site modules, and list those modules in the QPM service
manifest. See `qfw-services.yaml(5)` for the manifest contract:

```bash
man 5 qfw-services.yaml
```

The source checkout provides separate builders. Their complete options are
available through `--help`:

```bash
tools/dependencies/nwqsim/build.sh --help
tools/dependencies/tnqvm/build.sh --help
```

For example:

```bash
tools/dependencies/nwqsim/build.sh \
  --work-dir /var/tmp/qfw-dependencies/nwqsim \
  --prefix /opt/openqse/nwqsim \
  --rocm auto

tools/dependencies/nwqsim/build.sh \
  --work-dir /var/tmp/qfw-dependencies/nwqsim-cuda \
  --prefix /opt/openqse/nwqsim-cuda \
  --cuda on \
  --cuda-root /usr/local/cuda \
  --cuda-arch 86

tools/dependencies/tnqvm/build.sh \
  --work-dir /var/tmp/qfw-dependencies/tnqvm \
  --prefix /opt/openqse/tnqvm \
  --mpi-prefix /opt/openqse/openmpi \
  --rocm auto
```

NWQ-Sim applies one patch, `patches/common/nwqsim-sv-omp.patch`, so that its OpenMP
backend draws measurement random numbers once per run instead of once per thread.

OpenMPI 5.0.9 (bundled PRRTE 3.0.12 and OpenPMIx 5.0.9) crashes `mpirun` intermittently at job end:
the job-termination handler in `prun_common.c` wakes the main thread, which unregisters and frees the
event handler, before it calls the PMIx callback that still reads it. There is no QFw build script for
OpenMPI; when building it, apply `tools/dependencies/openmpi/patches/common/openmpi-prrte-evhandler-order.patch`
from the OpenMPI source root (`patch -p1 < ...`) before `make`. It calls the callback first.

NWQ-Sim also supports NVIDIA GPU acceleration via CUDA. Automatic CUDA selection
requires `nvcc` and CUDA headers. Use `--cuda on` to require that toolchain,
`--cuda off` to force the CPU build (default), or `--cuda auto` to auto-detect.
The `--cuda-root` option specifies the CUDA installation root (default: `/usr/local/cuda`),
and `--cuda-arch` selects the target GPU architecture by compute capability
(default: `80` for A100; use `86` for RTX A5000, etc.).

TNQVM applies the compatibility patch set used by both builds, followed by the
validated CPU or ROCm patch set. Automatic ROCm selection requires `hipcc`,
HIP headers, and hipBLAS. Use `--rocm on` to require that toolchain or
`--rocm off` to force the CPU build.

The builders install `circuit_runner.nwqsim` or `circuit_runner.tnqvm` beneath
the requested prefix. They do not write into the QFw source or installation.
The TNQVM builder installs TNQVM and its visitor libraries in the XACC prefix
because they are XACC plugins. Its top-level runner is a link to the executable
under that prefix, which lets XACC discover both its own plugins and TNQVM.
Create site modulefiles that expose the corresponding `bin` and library
directories, then verify them before starting QFw:

```bash
module load libfabric openmpi nwqsim
command -v prte pterm circuit_runner.nwqsim

module purge
module load libfabric openmpi tnqvm
command -v prte pterm circuit_runner.tnqvm
```

`qfw-setup(1)` performs the same module loading and executable validation for
the selected service, so applications do not run `module load` themselves.
