#!/usr/bin/env bash

set -euo pipefail

OMPI_VERSION="5.0.9"
OMPI_URL="https://download.open-mpi.org/release/open-mpi/v5.0/"\
"openmpi-${OMPI_VERSION}.tar.bz2"
OMPI_SHA256="dfb72762531170847af3e4a0f21d77d7b23cf36f67ce7ce9033659273677d80b"
PRRTE_REPOSITORY="https://github.com/hat-im/prrte.git"
PRRTE_BUNDLED_REF="v3.0.12"
PRRTE_REF="305abb05f299f6992fc466f6dca141aa498f5ae5"
WORK_DIR=""
INSTALL_PREFIX=""
OMPI_TARBALL=""
BUILD_JOBS="$(getconf _NPROCESSORS_ONLN 2>/dev/null || printf '2')"
CONFIGURE_ARGS=()

usage() {
	cat <<EOF
Usage: ${0##*/} --work-dir PATH --prefix PATH [options] [-- CONFIGURE_ARG...]

Build and install Open MPI ${OMPI_VERSION} with the PRRTE sources that
${PRRTE_REF} changes from the bundled PRRTE ${PRRTE_BUNDLED_REF}.

Required:
  --work-dir PATH       Dependency source and build workspace
  --prefix PATH         Open MPI installation prefix

Options:
  --tarball PATH        Local openmpi-${OMPI_VERSION}.tar.bz2 (default: download)
  --prrte-ref REF       PRRTE revision (default: ${PRRTE_REF})
  --jobs N              Parallel build jobs (default: ${BUILD_JOBS})
  -h, --help            Show this help

Arguments after -- are passed to Open MPI's configure.
EOF
}

fail() {
	printf '%s: %s\n' "${0##*/}" "$*" >&2
	exit 1
}

while (($#)); do
	case "$1" in
		--work-dir) WORK_DIR="${2:?missing value for --work-dir}"; shift 2 ;;
		--prefix) INSTALL_PREFIX="${2:?missing value for --prefix}"; shift 2 ;;
		--tarball) OMPI_TARBALL="${2:?missing value for --tarball}"; shift 2 ;;
		--prrte-ref) PRRTE_REF="${2:?missing value for --prrte-ref}"; shift 2 ;;
		--jobs) BUILD_JOBS="${2:?missing value for --jobs}"; shift 2 ;;
		-h|--help) usage; exit 0 ;;
		--) shift; CONFIGURE_ARGS=("$@"); break ;;
		*) fail "unknown argument: $1" ;;
	esac
done

[[ -n "${WORK_DIR}" ]] || fail "--work-dir is required"
[[ -n "${INSTALL_PREFIX}" ]] || fail "--prefix is required"
[[ "${BUILD_JOBS}" =~ ^[1-9][0-9]*$ ]] || fail "--jobs must be positive"
[[ -z "${OMPI_TARBALL}" || -f "${OMPI_TARBALL}" ]] || \
	fail "no such tarball: ${OMPI_TARBALL}"

SOURCE_ROOT="${WORK_DIR}/source"
OMPI_SOURCE="${SOURCE_ROOT}/openmpi-${OMPI_VERSION}"
BUNDLED_PRRTE="${OMPI_SOURCE}/3rd-party/prrte"
PRRTE_SOURCE="${SOURCE_ROOT}/prrte"
for source in "${OMPI_SOURCE}" "${PRRTE_SOURCE}"; do
	[[ ! -e "${source}" ]] || fail \
		"source directory already exists; use an empty --work-dir: ${source}"
done

mkdir -p "${SOURCE_ROOT}"
if [[ -z "${OMPI_TARBALL}" ]]; then
	OMPI_TARBALL="${SOURCE_ROOT}/openmpi-${OMPI_VERSION}.tar.bz2"
	curl -fsSL -o "${OMPI_TARBALL}" "${OMPI_URL}"
fi
printf '%s  %s\n' "${OMPI_SHA256}" "${OMPI_TARBALL}" | sha256sum -c --quiet - || \
	fail "${OMPI_TARBALL} is not the Open MPI ${OMPI_VERSION} release"
tar -C "${SOURCE_ROOT}" -xjf "${OMPI_TARBALL}"

git clone --no-checkout "${PRRTE_REPOSITORY}" "${PRRTE_SOURCE}"
git -C "${PRRTE_SOURCE}" merge-base --is-ancestor \
	"${PRRTE_BUNDLED_REF}" "${PRRTE_REF}" || \
	fail "PRRTE ${PRRTE_REF} does not descend from ${PRRTE_BUNDLED_REF}"
changed=()
while IFS= read -r path; do
	changed+=("${path}")
done < <(git -C "${PRRTE_SOURCE}" diff --name-only \
	"${PRRTE_BUNDLED_REF}" "${PRRTE_REF}")
((${#changed[@]})) || \
	fail "PRRTE ${PRRTE_REF} changes nothing from ${PRRTE_BUNDLED_REF}"
for path in "${changed[@]}"; do
	[[ "${path}" =~ ^src/.*\.[ch]$ ]] || fail \
		"PRRTE ${PRRTE_REF} changes ${path}; only C sources can replace bundled ones"
	cmp -s <(git -C "${PRRTE_SOURCE}" show "${PRRTE_BUNDLED_REF}:${path}") \
		"${BUNDLED_PRRTE}/${path}" || fail \
		"${BUNDLED_PRRTE}/${path} is not PRRTE ${PRRTE_BUNDLED_REF}'s"
done
for path in "${changed[@]}"; do
	git -C "${PRRTE_SOURCE}" show "${PRRTE_REF}:${path}" \
		> "${BUNDLED_PRRTE}/${path}"
done

cd "${OMPI_SOURCE}"
./configure --prefix="${INSTALL_PREFIX}" \
	${CONFIGURE_ARGS[@]+"${CONFIGURE_ARGS[@]}"}
make -j"${BUILD_JOBS}" all
make install

printf 'Open MPI %s with PRRTE %s installed in %s\n' \
	"${OMPI_VERSION}" "${PRRTE_REF}" "${INSTALL_PREFIX}"
