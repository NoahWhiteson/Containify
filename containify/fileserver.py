import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

import psutil

DEFAULT_CONFIG = {
	"host": "127.0.0.1",
	"port": 2121,
	"user": "containify",
	"password": "containify",
}


def _pid_file(root_dir: Path) -> Path:
	return root_dir / "fileserver.pid"


def _cfg_file(root_dir: Path) -> Path:
	return root_dir / "fileserver.json"


def read_config(root_dir: Path) -> Dict[str, object]:
	cfg_path = _cfg_file(root_dir)
	if cfg_path.exists():
		try:
			with cfg_path.open("r", encoding="utf-8") as f:
				cfg = json.load(f)
			return {**DEFAULT_CONFIG, **cfg}
		except Exception:
			return DEFAULT_CONFIG.copy()
	return DEFAULT_CONFIG.copy()


def write_config(root_dir: Path, cfg: Dict[str, object]) -> None:
	with _cfg_file(root_dir).open("w", encoding="utf-8") as f:
		json.dump(cfg, f, indent=2, sort_keys=True)


def is_running(root_dir: Path) -> Tuple[bool, Optional[int]]:
	pid_path = _pid_file(root_dir)
	if not pid_path.exists():
		return False, None
	try:
		pid = int(pid_path.read_text().strip())
		if pid <= 0:
			return False, None
		p = psutil.Process(pid)
		if not p.is_running():
			return False, None
		# Optional: verify command line contains fileserver-serve
		try:
			cmdline = " ".join(p.cmdline()).lower()
			if "fileserver-serve" not in cmdline and "fileserver" not in cmdline:
				# still accept as running
				pass
		except Exception:
			pass
		return True, pid
	except Exception:
		return False, None


def stop(root_dir: Path) -> bool:
	running, pid = is_running(root_dir)
	if not running or not pid:
		return False
	try:
		p = psutil.Process(pid)
		# Terminate children first
		for child in p.children(recursive=True):
			try:
				child.terminate()
			except Exception:
				pass
		p.terminate()
		try:
			p.wait(timeout=5)
		except psutil.TimeoutExpired:
			p.kill()
	except Exception:
		pass
	try:
		_pid_file(root_dir).unlink(missing_ok=True)
	except Exception:
		pass
	return True


def _windows_creation_flags() -> int:
	# DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
	return 0x00000008 | 0x00000200 | 0x08000000


def start_background(root_dir: Path, host: str, port: int, user: str, password: str) -> int:
	# Launch a detached Python process that runs the internal command 'fileserver-serve'
	python = sys.executable
	args = [
		python,
		"-m",
		"containify.cli",
		"fileserver-serve",
		"--root",
		str(root_dir),
		"--host",
		host,
		"--port",
		str(port),
		"--user",
		user,
		"--password",
		password,
	]
	if os.name == "nt":
		proc = psutil.Popen(args, creationflags=_windows_creation_flags(), close_fds=True)
	else:
		proc = psutil.Popen(args, preexec_fn=os.setsid, close_fds=True)
	# Give it a moment to bind port
	time.sleep(0.5)
	# Write PID
	_pid_file(root_dir).write_text(str(proc.pid))
	# Persist config
	write_config(root_dir, {"host": host, "port": port, "user": user, "password": password})
	return int(proc.pid)


def serve_forever(base_dir: str, host: str, port: int, user: str, password: str) -> None:
	from pyftpdlib.authorizers import DummyAuthorizer
	from pyftpdlib.handlers import FTPHandler
	from pyftpdlib.servers import FTPServer
	authorizer = DummyAuthorizer()
	authorizer.add_user(user, password, base_dir, perm="elradfmw")
	handler = FTPHandler
	handler.authorizer = authorizer
	handler.banner = "Containify FTP ready"
	server = FTPServer((host, port), handler)
	server.serve_forever()
