import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


DEFAULT_WINDOWS_ROOT = Path("C:/containify")
DEFAULT_UNIX_ROOT = Path("/containify")


def get_default_root_dir() -> Path:
	if os.name == "nt":
		return DEFAULT_WINDOWS_ROOT
	return DEFAULT_UNIX_ROOT


def get_root_dir(root_override: Optional[str] = None) -> Path:
	root = Path(root_override) if root_override else Path(os.environ.get("CONTAINIFY_ROOT", get_default_root_dir()))
	return root


def get_containers_dir(root_dir: Path) -> Path:
	return root_dir / "containers"


def get_container_dir(container_name: str, root_dir: Path) -> Path:
	return get_containers_dir(root_dir) / container_name


def ensure_dir(path: Path) -> None:
	path.mkdir(parents=True, exist_ok=True)


def validate_container_name(name: str) -> None:
	if not re.fullmatch(r"[a-zA-Z0-9._-]+", name):
		raise ValueError("Container name must be alphanumeric, dot, underscore, or dash")


def metadata_path(container_dir: Path) -> Path:
	return container_dir / "metadata.json"


def write_metadata(container_dir: Path, data: Dict[str, Any]) -> None:
	ensure_dir(container_dir)
	with metadata_path(container_dir).open("w", encoding="utf-8") as f:
		json.dump(data, f, indent=2, sort_keys=True)


def read_metadata(container_dir: Path) -> Dict[str, Any]:
	with metadata_path(container_dir).open("r", encoding="utf-8") as f:
		return json.load(f)


def now_iso() -> str:
	return datetime.now(timezone.utc).isoformat()


def python_version_str() -> str:
	return f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"


def parse_size_to_mb(value: str) -> int:
	"""
	Accepts integers as MB, or strings like 512m, 2g, 1gb.
	Returns integer MB.
	"""
	if isinstance(value, int):
		return value
	v = value.strip().lower()
	m = re.fullmatch(r"(\d+)([mg]b?|)", v)
	if not m:
		raise ValueError(f"Invalid size: {value}")
	num = int(m.group(1))
	unit = m.group(2)
	if unit in ("", None):
		return num
	if unit.startswith("m"):
		return num
	if unit.startswith("g"):
		return num * 1024
	raise ValueError(f"Invalid size unit: {value}")


def venv_python_path(container_dir: Path) -> Path:
	# Local backend venv lives under env/
	if os.name == "nt":
		return container_dir / "env" / "Scripts" / "python.exe"
	return container_dir / "env" / "bin" / "python"


def venv_paths_env(container_dir: Path) -> Dict[str, str]:
	env = os.environ.copy()
	venv_dir = container_dir / "env"
	if os.name == "nt":
		bin_dir = venv_dir / "Scripts"
		env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
	else:
		bin_dir = venv_dir / "bin"
		env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
	env["VIRTUAL_ENV"] = str(venv_dir)
	# Ensure pip installs into the venv and not user site
	env["PIP_USER"] = "0"
	return env
