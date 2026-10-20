# Synthetic imaging laboratory

Use only generated fixtures. This is a loopback-only, disposable development lab,
not a deployment for a clinic. It has no remote peers, DICOM listener, production
authentication or patient-file import command. OHIF upload is disabled. The
Orthanc remains on an internal backend network. Only the viewer/proxy joins an
edge bridge to publish loopback ports; port 18042 exposes STOW/QIDO/WADO and the
read-only lab identity, not the remaining Orthanc administrative API. Keep real
files out of this lab. Name/UID marker checks are accidental-misrouting guards,
not authentication or proof of synthetic provenance against a hostile caller.

From the repository root:

```sh
python -m pip install -r backend/requirements-imaging-review.txt
docker compose -f deploy/imaging-lab/compose.yaml config --quiet
docker compose -f deploy/imaging-lab/compose.yaml up -d
python -m backend.tools.imaging_lab_demo
```

Open <http://127.0.0.1:18080> for the synthetic worklist, or the generated study:
<http://127.0.0.1:18080/viewer?StudyInstanceUIDs=1.2.826.0.1.3680043.10.543.2001>.
The demo performs STOW-RS, QIDO-RS and WADO-RS before rechecking retrieved files.
No raw identifiers, pixel payloads or parser errors are printed in its JSON.

Stop and discard this lab's temporary data:

```sh
docker compose -f deploy/imaging-lab/compose.yaml down --volumes
```

The real browser/round-trip check runs in `imaging-phase2-ci.yml`. A Docker socket
denial in a managed executor does not mean those containers were started locally.
Image tags are pinned versions but remain mutable upstream; production supply
chain review and digest pinning are separate work.
