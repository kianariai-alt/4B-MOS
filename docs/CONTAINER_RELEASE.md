# Production container artifact

The root `Dockerfile` creates a portable backend release artifact. It installs
only runtime dependencies and includes the application, Alembic migrations and
read-only operational tools. Tests, development dependencies, local databases
and documentation are excluded from the image.

This artifact does not select a hosting provider, configure TLS, create a
database, migrate automatically, create the first administrator or authorize a
production deployment.

## Security contract

- The default base is the official `python:3.14.6-slim-bookworm` image.
- The application runs as numeric UID/GID `10001`, never as root.
- Bytecode and pip caches are disabled.
- The image declares only port `8000` and has a readiness health check.
- CI starts the image with all Linux capabilities dropped,
  `no-new-privileges`, a read-only root filesystem and a bounded temporary
  filesystem.
- Runtime data is not baked into the image. A reviewed database service or an
  explicitly mounted `/data` volume is required.

For a release, resolve the approved official base image to an immutable digest
and supply it as the build argument. Do not rely on a moving tag for a preserved
release record:

```sh
docker build --pull \
  --build-arg PYTHON_IMAGE='python:3.14.6-slim-bookworm@sha256:<approved-index-digest>' \
  --tag 4b-mos-backend:<release> .
```

Record both the resulting image digest and source commit. The default tag keeps
CI reproducible enough to detect build/runtime breakage, but it is not a supply-
chain attestation or vulnerability certification.

## Controlled startup sequence

Use an environment file stored outside the repository with restricted
permissions. Never put a real signing key, database password or patient data in
the image, command history, CI variables used by untrusted pull requests, logs
or screenshots.

1. Drain every old worker and preserve the verified backup/recovery evidence.
2. Run the migration as a one-shot command using the exact release image:

   ```sh
   docker run --rm \
     --read-only --tmpfs /tmp:rw,noexec,nosuid,size=64m \
     --env-file /protected/4bmos-production.env \
     --mount type=volume,source=4bmos-data,target=/data \
     4b-mos-backend:<release> python -m alembic upgrade head
   ```

3. Complete the reviewed isolated first-administrator procedure when required,
   then ensure public bootstrap is disabled.
4. Run `python -m backend.tools.release_preflight` from the same image and
   environment. Preserve its result with the release record.
5. Start the API as UID/GID `10001` with a read-only root filesystem, dropped
   capabilities, `no-new-privileges` and only the required writable database or
   temporary mounts.
6. Verify `/api/v1/health` and `/api/v1/health/ready`, then enable traffic
   through the reviewed HTTPS reverse proxy. Do not expose port 8000 directly
   to the public internet.

For PostgreSQL, omit the `/data` mount and inject the reviewed
`postgresql+psycopg://...` connection URL through the deployment secret system.
For SQLite, the private environment must use an absolute container path such as
`sqlite:////data/4bmos.db`; keep the volume on protected storage and retain the
documented single-writer limitations.

Migrations deliberately do not run in the normal container `CMD`. Running an
upgrade independently prevents every API replica from racing to modify the
schema and keeps database changes inside the maintenance window.

## CI smoke gate

Every pull request builds the image, migrates a fresh disposable SQLite volume,
starts the API in production mode and verifies:

- readiness and liveness responses;
- the packaged `/app/` clinical console and its no-store asset policy;
- production documentation is disabled;
- runtime UID is `10001`;
- the root filesystem is read-only; and
- startup succeeds with all capabilities dropped and `no-new-privileges`.

The stable `Backend CI` summary now requires this smoke job as well as both
SQLite/Python and PostgreSQL/Python matrices. The disposable credentials and
database contain no production or patient data.

## Limitations

The smoke gate is not registry signing, SBOM generation, CVE review, penetration
testing, load/failover validation, TLS or proxy validation, encrypted backup
validation, monitoring/alerting, browser penetration testing, managed PostgreSQL
certification or a hosting approval. Those require separate controls for the
selected environment.
