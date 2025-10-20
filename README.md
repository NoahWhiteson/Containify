# Containify

Containify is a simple, installable Python CLI to create isolated, folder-backed environments ("containers") under a dedicated directory, with optional Docker-based resource limits.

## Quick start

- Install locally (editable):

```bash
pip install git+https://github.com/NoahWhiteson/Containify.git
```

- Create a local container:

```bash
containify create myapp --ram 1024 --storage 2048 --cpu 50
```

- Open a shell inside it (local backend):

```bash
containify shell myapp
```

- Run a command in it:

```bash
containify run myapp -- python -c "print('hi')"
```

- Install packages into it:

```bash
containify install myapp requests fastapi
```

- Use Docker backend (requires Docker daemon):

```bash
containify create myapp --backend docker --ram 1024 --cpu 50
containify shell myapp
```

## Paths

By default, containers live under `C:\\containify\\containers` on Windows and `/containify/containers` on Unix. Override with `--root` or `CONTAINIFY_ROOT`.

## Notes

- Local backend isolates via per-container virtualenv and workspace folder. Hard resource limits are best-effort locally and fully enforced with Docker.
