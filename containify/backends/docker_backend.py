import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

try:
	import docker  # type: ignore
except Exception:  # pragma: no cover - docker optional
	docker = None

from ..utils import ensure_dir, get_container_dir, now_iso, python_version_str


IMAGE = os.environ.get("CONTAINIFY_DOCKER_IMAGE", "python:3.11-slim")


def _client():
	if docker is None:
		raise RuntimeError("docker SDK not available. Install docker and python package 'docker'.")
	return docker.from_env()


def _nano_cpus_for_percent(percent: int) -> int:
	cpus = psutil.cpu_count(logical=True) or 1
	# nano_cpus is absolute CPU time limit across all CPUs
	return int((percent / 100.0) * cpus * 1_000_000_000)


def _base_metadata(name: str, root_dir: Path, limits: Dict[str, int], container_id: str) -> Dict[str, Any]:
	container_dir = get_container_dir(name, root_dir)
	workspace_dir = container_dir / "workspace"
	return {
		"name": name,
		"backend": "docker",
		"limits": limits,
		"paths": {
			"root": str(root_dir),
			"container_dir": str(container_dir),
			"workspace_dir": str(workspace_dir),
		},
		"backend_data": {"docker": {"container_id": container_id, "image": IMAGE}},
		"created_at": now_iso(),
		"python_version": python_version_str(),
	}


def create_docker_container(name: str, root_dir: Path, limits: Dict[str, int]) -> Dict[str, Any]:
	client = _client()
	container_dir = get_container_dir(name, root_dir)
	if container_dir.exists():
		raise FileExistsError(f"Container '{name}' already exists at {container_dir}")
	ensure_dir(container_dir)
	workspace = container_dir / "workspace"
	ensure_dir(workspace)
	# Pull image if needed
	client.images.pull(IMAGE)
	nano_cpus = _nano_cpus_for_percent(limits.get("cpu_percent", 100))
	mem_limit = f"{limits.get('memory_mb', 0)}m" if limits.get("memory_mb") else None
	container = client.containers.create(
		IMAGE,
		name=f"containify-{name}",
		stdin_open=True,
		tty=True,
		working_dir="/workspace",
		volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
		mem_limit=mem_limit,
		nano_cpus=nano_cpus if nano_cpus > 0 else None,
		command=["sleep", "infinity"],
	)
	container.reload()
	md = _base_metadata(name, root_dir, limits, container.id)
	with (container_dir / "metadata.json").open("w", encoding="utf-8") as f:
		json.dump(md, f, indent=2, sort_keys=True)
	return md


def list_docker_containers(root_dir: Path) -> List[Dict[str, Any]]:
	containers_dir = (root_dir / "containers")
	if not containers_dir.exists():
		return []
	items: List[Dict[str, Any]] = []
	for child in containers_dir.iterdir():
		md_file = child / "metadata.json"
		if md_file.exists():
			with md_file.open("r", encoding="utf-8") as f:
				md = json.load(f)
				if md.get("backend") == "docker":
					items.append(md)
	return items


def read_docker_metadata(name: str, root_dir: Path) -> Dict[str, Any]:
	container_dir = get_container_dir(name, root_dir)
	md_file = container_dir / "metadata.json"
	if not md_file.exists():
		raise FileNotFoundError(f"Docker container '{name}' not found")
	with md_file.open("r", encoding="utf-8") as f:
		return json.load(f)


def _ensure_running(container_id: str):
	client = _client()
	container = client.containers.get(container_id)
	if container.status != "running":
		container.start()
	return container


def _get_container(name: str, root_dir: Path):
	md = read_docker_metadata(name, root_dir)
	container_id = md.get("backend_data", {}).get("docker", {}).get("container_id")
	if not container_id:
		raise RuntimeError("Missing docker container id in metadata")
	client = _client()
	return client.containers.get(container_id)


def run_in_docker(name: str, root_dir: Path, command: List[str]) -> int:
	md = read_docker_metadata(name, root_dir)
	container_id = md.get("backend_data", {}).get("docker", {}).get("container_id")
	if not container_id:
		raise RuntimeError("Missing docker container id in metadata")
	container = _ensure_running(container_id)
	exec_res = container.exec_run(command, stdout=True, stderr=True, stdin=False, tty=False)
	# docker SDK returns combined output; we print it
	output = exec_res.output
	if output:
		try:
			print(output.decode("utf-8"), end="")
		except Exception:
			# bytes as-is
			print(output)
	return int(exec_res.exit_code or 0)


def run_in_docker_shell(name: str, root_dir: Path, command_str: str) -> int:
	container = _get_container(name, root_dir)
	if container.status != "running":
		container.start()
	exec_res = container.exec_run(["/bin/sh", "-lc", command_str], stdout=True, stderr=True, stdin=False, tty=False)
	out = exec_res.output
	if out:
		try:
			print(out.decode("utf-8"), end="")
		except Exception:
			print(out)
	return int(exec_res.exit_code or 0)


def shell_in_docker(name: str, root_dir: Path) -> int:
	md = read_docker_metadata(name, root_dir)
	container_id = md.get("backend_data", {}).get("docker", {}).get("container_id")
	if not container_id:
		raise RuntimeError("Missing docker container id in metadata")
	container = _ensure_running(container_id)
	# Try to launch an interactive shell using docker CLI for proper TTY
	docker_cli = os.environ.get("DOCKER_CLI", "docker")
	import subprocess
	return subprocess.call([docker_cli, "exec", "-it", container.id, "/bin/bash"])  # falls back to bash


def install_in_docker(name: str, root_dir: Path, packages: List[str]) -> int:
	md = read_docker_metadata(name, root_dir)
	container_id = md.get("backend_data", {}).get("docker", {}).get("container_id")
	if not container_id:
		raise RuntimeError("Missing docker container id in metadata")
	container = _ensure_running(container_id)
	cmd = ["python", "-m", "pip", "install", "--upgrade", "pip"]
	exec_res = container.exec_run(cmd)
	if exec_res.exit_code not in (0, None):
		return int(exec_res.exit_code)
	if packages:
		exec_res = container.exec_run(["python", "-m", "pip", "install", *packages])
		return int(exec_res.exit_code or 0)
	return 0


def delete_docker_container(name: str, root_dir: Path) -> None:
	md = read_docker_metadata(name, root_dir)
	container_id = md.get("backend_data", {}).get("docker", {}).get("container_id")
	if container_id:
		client = _client()
		try:
			c = client.containers.get(container_id)
			c.remove(force=True)
		except Exception:
			pass
	# delete files on host
	import shutil
	container_dir = get_container_dir(name, root_dir)
	shutil.rmtree(container_dir, ignore_errors=True)


def start_docker_container(name: str, root_dir: Path) -> None:
	c = _get_container(name, root_dir)
	if c.status != "running":
		c.start()


def stop_docker_container(name: str, root_dir: Path) -> None:
	c = _get_container(name, root_dir)
	try:
		c.stop(timeout=10)
	except Exception:
		pass


def docker_container_stats(name: str, root_dir: Path) -> Dict[str, Any]:
	c = _get_container(name, root_dir)
	try:
		st = c.stats(stream=False)
		mem_usage = int(st.get('memory_stats', {}).get('usage', 0))
		mem_limit = int(st.get('memory_stats', {}).get('limit', 0))
		cpu_percent = 0.0
		cpu = st.get('cpu_stats', {})
		pcpu = st.get('precpu_stats', {})
		# approximate CPU percent
		total = float(cpu.get('cpu_usage', {}).get('total_usage', 0)) - float(pcpu.get('cpu_usage', {}).get('total_usage', 0))
		system = float(cpu.get('system_cpu_usage', 0)) - float(pcpu.get('system_cpu_usage', 0))
		n_cpus = int(cpu.get('online_cpus') or cpu.get('cpu_usage', {}).get('percpu_usage') and len(cpu.get('cpu_usage', {}).get('percpu_usage')) or 1)
		if system > 0 and n_cpus > 0:
			cpu_percent = (total / system) * n_cpus * 100.0
		c.reload()
		started_at = c.attrs.get('State', {}).get('StartedAt')
		uptime_s = None
		if started_at and c.status == 'running':
			try:
				dt = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
				uptime_s = int((datetime.now(timezone.utc) - dt).total_seconds())
			except Exception:
				uptime_s = None
		return {
			"cpu_percent": cpu_percent,
			"mem_usage_bytes": mem_usage,
			"mem_limit_bytes": mem_limit,
			"uptime_seconds": uptime_s,
			"status": c.status,
		}
	except Exception:
		return {"cpu_percent": 0.0, "mem_usage_bytes": 0, "mem_limit_bytes": 0, "uptime_seconds": None, "status": c.status}
