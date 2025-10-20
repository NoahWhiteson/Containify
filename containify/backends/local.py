import json
import os
import subprocess
import venv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import psutil

from ..utils import (
	ensure_dir,
	get_container_dir,
	get_containers_dir,
	now_iso,
	python_version_str,
	venv_paths_env,
	venv_python_path,
)


def _base_metadata(name: str, root_dir: Path, limits: Dict[str, int]) -> Dict[str, Any]:
	container_dir = get_container_dir(name, root_dir)
	workspace_dir = container_dir / "workspace"
	return {
		"name": name,
		"backend": "local",
		"limits": limits,
		"paths": {
			"root": str(root_dir),
			"container_dir": str(container_dir),
			"workspace_dir": str(workspace_dir),
		},
		"backend_data": {},
		"created_at": now_iso(),
		"python_version": python_version_str(),
	}


def create_local_container(name: str, root_dir: Path, limits: Dict[str, int]) -> Dict[str, Any]:
	container_dir = get_container_dir(name, root_dir)
	if container_dir.exists():
		raise FileExistsError(f"Container '{name}' already exists at {container_dir}")
	ensure_dir(container_dir)
	ensure_dir(container_dir / "workspace")
	# Create venv
	venv_dir = container_dir / "env"
	builder = venv.EnvBuilder(with_pip=True, clear=False)
	builder.create(str(venv_dir))
	md = _base_metadata(name, root_dir, limits)
	with (container_dir / "metadata.json").open("w", encoding="utf-8") as f:
		json.dump(md, f, indent=2, sort_keys=True)
	return md


def list_local_containers(root_dir: Path) -> List[Dict[str, Any]]:
	containers_dir = get_containers_dir(root_dir)
	if not containers_dir.exists():
		return []
	items: List[Dict[str, Any]] = []
	for child in containers_dir.iterdir():
		md_file = child / "metadata.json"
		if md_file.exists():
			with md_file.open("r", encoding="utf-8") as f:
				items.append(json.load(f))
	return items


def read_local_metadata(name: str, root_dir: Path) -> Dict[str, Any]:
	container_dir = get_container_dir(name, root_dir)
	md_file = container_dir / "metadata.json"
	if not md_file.exists():
		raise FileNotFoundError(f"Local container '{name}' not found")
	with md_file.open("r", encoding="utf-8") as f:
		return json.load(f)


def _venv_env(container_dir: Path) -> Dict[str, str]:
	return venv_paths_env(container_dir)


def run_in_local(name: str, root_dir: Path, command: List[str]) -> int:
	container_dir = get_container_dir(name, root_dir)
	if not (container_dir / "metadata.json").exists():
		raise FileNotFoundError(f"Local container '{name}' not found")
	env = _venv_env(container_dir)
	cwd = container_dir / "workspace"
	ensure_dir(cwd)
	proc = subprocess.Popen(command, cwd=str(cwd), env=env)
	return proc.wait()


def run_in_local_shell(name: str, root_dir: Path, command_str: str) -> int:
	container_dir = get_container_dir(name, root_dir)
	if not (container_dir / "metadata.json").exists():
		raise FileNotFoundError(f"Local container '{name}' not found")
	env = _venv_env(container_dir)
	cwd = container_dir / "workspace"
	ensure_dir(cwd)
	if os.name == "nt":
		cmd = [os.environ.get("COMSPEC", "cmd.exe"), "/C", command_str]
	else:
		cmd = [os.environ.get("SHELL", "/bin/bash"), "-lc", command_str]
	proc = subprocess.Popen(cmd, cwd=str(cwd), env=env)
	return proc.wait()


def shell_in_local(name: str, root_dir: Path) -> int:
	container_dir = get_container_dir(name, root_dir)
	if not (container_dir / "metadata.json").exists():
		raise FileNotFoundError(f"Local container '{name}' not found")
	env = _venv_env(container_dir)
	cwd = container_dir / "workspace"
	ensure_dir(cwd)
	if os.name == "nt":
		shell = os.environ.get("COMSPEC", "cmd.exe")
		proc = subprocess.Popen([shell], cwd=str(cwd), env=env)
	else:
		shell = os.environ.get("SHELL", "/bin/bash")
		proc = subprocess.Popen([shell], cwd=str(cwd), env=env)
	return proc.wait()


def install_in_local(name: str, root_dir: Path, packages: List[str]) -> int:
	container_dir = get_container_dir(name, root_dir)
	if not (container_dir / "metadata.json").exists():
		raise FileNotFoundError(f"Local container '{name}' not found")
	python = venv_python_path(container_dir)
	cmd = [str(python), "-m", "pip", "install", "--upgrade", "pip"]
	subprocess.check_call(cmd, cwd=str(container_dir))
	if packages:
		cmd = [str(python), "-m", "pip", "install", *packages]
		return subprocess.call(cmd, cwd=str(container_dir))
	return 0


def delete_local_container(name: str, root_dir: Path) -> None:
	container_dir = get_container_dir(name, root_dir)
	if not container_dir.exists():
		return
	# Best-effort recursive delete
	import shutil
	shutil.rmtree(container_dir, ignore_errors=True)


def start_local_container(name: str, root_dir: Path) -> None:
	# no-op: local containers are directory + venv. Startup handled by startup command
	return None


def stop_local_container(name: str, root_dir: Path) -> None:
	# best-effort: kill any known startup process recorded in metadata
	try:
		md = read_local_metadata(name, root_dir)
		pid = (md.get("backend_state", {}) or {}).get("startup_pid")
		if pid:
			p = psutil.Process(int(pid))
			p.terminate()
			try:
				p.wait(timeout=5)
			except psutil.TimeoutExpired:
				p.kill()
	except Exception:
		pass


def local_container_stats(name: str, root_dir: Path) -> Dict[str, Any]:
	# Best-effort from recorded PID, else zeros
	try:
		md = read_local_metadata(name, root_dir)
		pid = (md.get("backend_state", {}) or {}).get("startup_pid")
		if pid:
			p = psutil.Process(int(pid))
			cpu = p.cpu_percent(interval=0.1)
			mem = p.memory_info().rss
			uptime = None
			if p.create_time():
				uptime = int((datetime.now(timezone.utc).timestamp() - p.create_time()))
			return {"cpu_percent": cpu, "mem_usage_bytes": int(mem), "uptime_seconds": uptime, "status": "running" if p.is_running() else "stopped"}
	except Exception:
		pass
	return {"cpu_percent": 0.0, "mem_usage_bytes": 0, "uptime_seconds": None, "status": "unknown"}
