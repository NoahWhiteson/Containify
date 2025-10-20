import json
from pathlib import Path
from typing import Any, Dict

from .fileserver import DEFAULT_CONFIG as FS_DEFAULT


DEFAULT_SETTINGS: Dict[str, Any] = {
	"theme": {
		"name": "default",
		"colors": {
			"hr": "bright_black",
			"heading": "cyan",
			"label": "bright_white",
			"value": "white",
			"index": "green",
			"prompt": "yellow",
			"ok": "green",
			"warn": "yellow",
			"err": "red",
		},
	},
	"defaults": {
		"backend": "local",
		"ram_mb": 512,
		"storage_mb": 1024,
		"cpu_percent": 100,
	},
	"ftp": FS_DEFAULT,
}


def _settings_path(root_dir: Path) -> Path:
	return root_dir / "settings.json"


def read_settings(root_dir: Path) -> Dict[str, Any]:
	path = _settings_path(root_dir)
	if not path.exists():
		return json.loads(json.dumps(DEFAULT_SETTINGS))
	try:
		with path.open("r", encoding="utf-8") as f:
			data = json.load(f)
		# Deep-merge defaults
		settings = json.loads(json.dumps(DEFAULT_SETTINGS))
		def merge(a: Dict[str, Any], b: Dict[str, Any]):
			for k, v in b.items():
				if isinstance(v, dict) and isinstance(a.get(k), dict):
					merge(a[k], v)
				else:
					a[k] = v
		merge(settings, data)
		return settings
	except Exception:
		return json.loads(json.dumps(DEFAULT_SETTINGS))


def write_settings(root_dir: Path, settings: Dict[str, Any]) -> None:
	path = _settings_path(root_dir)
	with path.open("w", encoding="utf-8") as f:
		json.dump(settings, f, indent=2, sort_keys=True)
