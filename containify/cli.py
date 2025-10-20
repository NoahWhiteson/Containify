import json
from typing import Optional

import click
import questionary as q
from pyfiglet import figlet_format

from .resources import get_system_resources
from .utils import (
	get_root_dir,
	get_containers_dir,
	ensure_dir,
	parse_size_to_mb,
	validate_container_name,
	get_container_dir,
)
from .backends import (
	create_local_container,
	delete_local_container,
	install_in_local,
	list_local_containers,
	run_in_local,
	shell_in_local,
	read_local_metadata,
	create_docker_container,
	delete_docker_container,
	install_in_docker,
	list_docker_containers,
	run_in_docker,
	shell_in_docker,
	read_docker_metadata,
	run_in_docker_shell,
	run_in_local_shell,
	start_local_container,
	stop_local_container,
	local_container_stats,
	start_docker_container,
	stop_docker_container,
	docker_container_stats,
)
from .fileserver import read_config as fs_read_config, start_background as fs_start, stop as fs_stop, is_running as fs_is_running, serve_forever as fs_serve
from .settings import read_settings, write_settings


def _resolve_backend(name: str, root_dir):
	# Prefer exact metadata presence to decide backend deterministically
	try:
		md = read_local_metadata(name, root_dir)
		if md.get("backend") == "local":
			return "local"
	except Exception:
		pass
	try:
		md = read_docker_metadata(name, root_dir)
		if md.get("backend") == "docker":
			return "docker"
	except Exception:
		pass
	return None


@click.group()
@click.version_option()
@click.option("--root", "root_override", type=click.Path(path_type=str), required=False, help="Override containify root directory")
@click.pass_context
def cli(ctx: click.Context, root_override: Optional[str]):
	root_dir = get_root_dir(root_override)
	ensure_dir(get_containers_dir(root_dir))
	ctx.obj = {"root": root_dir}


@cli.command()
@click.pass_context
def help(ctx: click.Context):
	"""Show top-level help and commands."""
	click.echo(ctx.parent.get_help() if ctx.parent else ctx.get_help())


def _theme(colors):
	return {
		"hr": colors.get("hr", "bright_black"),
		"heading": colors.get("heading", "cyan"),
		"label": colors.get("label", "bright_white"),
		"value": colors.get("value", "white"),
		"index": colors.get("index", "green"),
		"prompt": colors.get("prompt", "yellow"),
		"ok": colors.get("ok", "green"),
		"warn": colors.get("warn", "yellow"),
		"err": colors.get("err", "red"),
	}


def _hr(t):
	click.echo(click.style("-" * 60, fg=t["hr"]))


def _heading(t, text: str):
	click.echo(click.style(text, fg=t["heading"], bold=True))


def _kv(t, label: str, value):
	click.echo(f"  {click.style(label+':', fg=t['label'], bold=True)} {click.style(str(value), fg=t['value'])}")


def _q_select(message: str, choices: list, default=None):
	if default is None:
		return q.select(message, choices=choices).unsafe_ask()
	return q.select(message, choices=choices, default=default).unsafe_ask()


def _q_text(message: str, default: Optional[str] = None):
	if default is None:
		default = ""
	return q.text(message, default=default).unsafe_ask()


def _q_confirm(message: str, default: bool = False):
	return q.confirm(message, default=default).unsafe_ask()


def _open_path(path: str) -> None:
	import os
	import subprocess
	try:
		if os.name == "nt":
			os.startfile(path)  # type: ignore[attr-defined]
		else:
			subprocess.Popen(["xdg-open", path])
	except Exception:
		pass


@cli.command()
@click.pass_context
def enter(ctx: click.Context):
	"""Interactive control panel."""
	root_dir = ctx.obj["root"]
	settings = read_settings(root_dir)
	t = _theme(settings.get("theme", {}).get("colors", {}))
	while True:
		click.clear()
		# ASCII art title
		try:
			ascii_title = figlet_format("Containify", font="Standard")
			click.echo(click.style(ascii_title, fg=t["heading"]))
		except Exception:
			_heading(t, "Containify Control Panel")
		_hr(t)
		main_choice = _q_select(
			"Select",
			[
				q.Choice(title="Containers", value="containers"),
				q.Choice(title="Create Container", value="create"),
				q.Choice(title="Status", value="status"),
				q.Choice(title="File System (FTP)", value="ftp"),
				q.Choice(title="Open Containers Folder", value="open_root"),
				q.Choice(title="About", value="about"),
				q.Choice(title="Settings", value="settings"),
				q.Choice(title="Quit", value="quit"),
			],
		)
		if main_choice == "containers":
			click.clear()
			_heading(t, "Containers")
			items = list_local_containers(root_dir) + list_docker_containers(root_dir)
			if not items:
				click.echo(click.style("No containers", fg=t["hr"]))
				_q_select("Continue", [q.Choice(title="Back", value="back")])
				continue
			# map names to metadata
			name_to_md = { (md.get('name')): md for md in items }
			choices = [
				q.Choice(
					title=f"{md.get('name')} [{md.get('backend')}] -> {(md.get('paths', {}) or {}).get('workspace_dir')}",
					value=md.get('name'),
				)
				for md in items
			]
			choices.append(q.Choice(title="Back", value=None))
			selected_name = _q_select("Select container", choices)
			if not selected_name:
				continue
			md = name_to_md.get(selected_name)
			if not isinstance(md, dict):
				continue
			while True:
				click.clear()
				_heading(t, f"Container: {md.get('name')}")
				_hr(t)
				_kv(t, "Backend", md.get("backend"))
				_kv(t, "Workspace", (md.get("paths", {}) or {}).get("workspace_dir"))
				lim = md.get("limits", {}) or {}
				_kv(t, "CPU %", lim.get("cpu_percent"))
				_kv(t, "RAM MB", lim.get("memory_mb"))
				_kv(t, "Storage MB", lim.get("storage_mb"))
				_hr(t)
				action = _q_select(
					"Action",
					[
						q.Choice(title="Enter shell", value="shell"),
						q.Choice(title="Run command", value="run"),
						q.Choice(title="Install packages", value="install"),
						q.Choice(title="Open workspace folder", value="open_ws"),
						q.Choice(title="Start", value="start"),
						q.Choice(title="Stop", value="stop"),
						q.Choice(title="Set startup command", value="startup"),
						q.Choice(title="Rename container", value="rename"),
						q.Choice(title="Edit limits", value="limits"),
						q.Choice(title="Delete container", value="delete"),
						q.Choice(title="Back", value="back"),
					],
				)
				if action == "shell":
					backend = md.get("backend")
					name = md.get("name")
					if backend == "local":
						code = shell_in_local(name, root_dir)
						click.get_current_context().exit(code)
					else:
						code = shell_in_docker(name, root_dir)
						click.get_current_context().exit(code)
				elif action == "run":
					cmd = _q_text("Command")
					backend = md.get("backend")
					name = md.get("name")
					if backend == "local":
						click.get_current_context().exit(run_in_local_shell(name, root_dir, cmd))
					else:
						click.get_current_context().exit(run_in_docker_shell(name, root_dir, cmd))
				elif action == "install":
					pkgs = _q_text("Packages (space-separated)")
					backend = md.get("backend")
					name = md.get("name")
					if backend == "local":
						click.get_current_context().exit(install_in_local(name, root_dir, pkgs.split()))
					else:
						click.get_current_context().exit(install_in_docker(name, root_dir, pkgs.split()))
				elif action == "open_ws":
					ws = (md.get("paths", {}) or {}).get("workspace_dir")
					if ws:
						_open_path(ws)
				elif action == "start":
					if md.get("backend") == "local":
						start_local_container(md.get("name"), root_dir)
					else:
						start_docker_container(md.get("name"), root_dir)
					click.echo(click.style("Started", fg=t["ok"]))
				elif action == "stop":
					if md.get("backend") == "local":
						stop_local_container(md.get("name"), root_dir)
					else:
						stop_docker_container(md.get("name"), root_dir)
					click.echo(click.style("Stopped", fg=t["ok"]))
				elif action == "startup":
					cur = (md.get("backend_state", {}) or {}).get("startup_command")
					new_cmd = _q_text("Startup command (empty to clear)", default=str(cur or ""))
					import json as _json
					md_file = get_container_dir(md.get("name"), root_dir) / "metadata.json"
					data = _json.loads(md_file.read_text(encoding="utf-8"))
					backend_state = (data.get("backend_state") or {})
					backend_state["startup_command"] = new_cmd.strip() or None
					data["backend_state"] = backend_state
					md_file.write_text(_json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
					md = data
					click.echo(click.style("Saved", fg=t["ok"]))
				elif action == "rename":
					new_name = _q_text("New name", default=str(md.get("name")))
					validate_container_name(new_name)
					if new_name != md.get("name"):
						# Move folder and update metadata
						old_dir = get_container_dir(md.get("name"), root_dir)
						new_dir = get_container_dir(new_name, root_dir)
						import os, shutil
						if os.path.exists(new_dir):
							click.echo(click.style("Target name already exists", fg=t["err"]))
						else:
							shutil.move(str(old_dir), str(new_dir))
							# Update metadata name
							import json as _json
							md_file = new_dir / "metadata.json"
							data = _json.loads(md_file.read_text(encoding="utf-8"))
							data["name"] = new_name
							md_file.write_text(_json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
							md = data
							click.echo(click.style("Renamed", fg=t["ok"]))
				elif action == "limits":
					lim = md.get("limits", {}) or {}
					new_ram = _q_text("RAM (e.g. 512m)", default=str(lim.get("memory_mb")))
					new_storage = _q_text("Storage (e.g. 1g)", default=str(lim.get("storage_mb")))
					new_cpu = _q_text("CPU %", default=str(lim.get("cpu_percent")))
					lim2 = {"memory_mb": parse_size_to_mb(new_ram), "storage_mb": parse_size_to_mb(new_storage), "cpu_percent": int(new_cpu)}
					# Persist to metadata; enforcement depends on backend
					import json as _json
					md_file = get_container_dir(md.get("name"), root_dir) / "metadata.json"
					data = _json.loads(md_file.read_text(encoding="utf-8"))
					data["limits"] = lim2
					md_file.write_text(_json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
					md = data
					click.echo(click.style("Limits updated", fg=t["ok"]))
				elif action == "delete":
					if _q_confirm("Confirm delete?", default=False):
						if md.get("backend") == "local":
							delete_local_container(md.get("name"), root_dir)
						else:
							delete_docker_container(md.get("name"), root_dir)
						click.echo(click.style("Deleted", fg=t["ok"]))
						_q_select("Continue", [q.Choice(title="Back", value="back")])
						break
				else:
					break
		elif main_choice == "create":
			click.clear()
			_heading(t, "Create Container")
			name = _q_text("Name")
			validate_container_name(name)
			backend = _q_select("Backend", [q.Choice("local"), q.Choice("docker")], default=read_settings(root_dir)["defaults"]["backend"])
			ram = _q_text("RAM (e.g. 512m or 1g)", default=str(read_settings(root_dir)["defaults"]["ram_mb"]))
			storage = _q_text("Storage (e.g. 1g)", default=str(read_settings(root_dir)["defaults"]["storage_mb"]))
			cpu_str = _q_text("CPU % (1-100)", default=str(read_settings(root_dir)["defaults"]["cpu_percent"]))
			limits = {"memory_mb": parse_size_to_mb(ram), "storage_mb": parse_size_to_mb(storage), "cpu_percent": int(cpu_str)}
			if backend == "local":
				md = create_local_container(name, root_dir, limits)
			else:
				md = create_docker_container(name, root_dir, limits)
			click.echo(click.style("Created", fg=t["ok"]))
			_q_select("Continue", [q.Choice(title="Back", value="back")])
		elif main_choice == "status":
			click.clear()
			_heading(t, "Status")
			resources = get_system_resources(root_dir)
			items = list_local_containers(root_dir) + list_docker_containers(root_dir)
			_hr(t)
			_heading(t, "System")
			_kv(t, "Total RAM (MB)", resources.get("total_ram_mb"))
			_kv(t, "Available RAM (MB)", resources.get("available_ram_mb"))
			_kv(t, "CPUs (logical)", resources.get("cpu_count_logical"))
			_kv(t, "CPUs (physical)", resources.get("cpu_count_physical"))
			_kv(t, "Disk Total (GB)", resources.get("disk_total_gb"))
			_kv(t, "Disk Free (GB)", resources.get("disk_free_gb"))
			_hr(t)
			_heading(t, "Containers")
			_kv(t, "Total", len(items))
			_kv(t, "Local", len([i for i in items if i.get("backend") == "local"]))
			_kv(t, "Docker", len([i for i in items if i.get("backend") == "docker"]))
			agg_cpu = []
			agg_mem = []
			for md in items:
				name = md.get("name")
				if md.get("backend") == "local":
					st = local_container_stats(name, root_dir)
				else:
					st = docker_container_stats(name, root_dir)
				agg_cpu.append(float(st.get("cpu_percent") or 0.0))
				agg_mem.append(int(st.get("mem_usage_bytes") or 0))
				click.echo(click.style("\n- " + name, fg=t["value"], bold=True))
				_kv(t, "Status", st.get("status"))
				_kv(t, "CPU %", f"{st.get('cpu_percent'):.1f}")
				_kv(t, "Mem (MB)", int((st.get("mem_usage_bytes") or 0) / (1024*1024)))
				upt = st.get("uptime_seconds")
				_kv(t, "Uptime", upt if upt is not None else "-")
			# Aggregates
			_hr(t)
			_heading(t, "Aggregates")
			if agg_cpu:
				_kv(t, "CPU avg%", f"{(sum(agg_cpu)/len(agg_cpu)):.1f}")
				_kv(t, "CPU max%", f"{max(agg_cpu):.1f}")
				_kv(t, "CPU min%", f"{min(agg_cpu):.1f}")
			if agg_mem:
				_kv(t, "Mem total MB", int(sum(agg_mem)/(1024*1024)))
				_kv(t, "Mem max MB", int(max(agg_mem)/(1024*1024)))
				_kv(t, "Mem min MB", int(min(agg_mem)/(1024*1024)))
			_q_select("Continue", [q.Choice(title="Back", value="back")])
		elif main_choice == "ftp":
			click.clear()
			_heading(t, "File System (FTP)")
			cfg = fs_read_config(root_dir)
			running, pid = fs_is_running(root_dir)
			_kv(t, "Status", "running" if running else "stopped")
			if running:
				_kv(t, "PID", pid)
			_kv(t, "Host", cfg.get("host"))
			_kv(t, "Port", cfg.get("port"))
			_kv(t, "Username", cfg.get("user"))
			_kv(t, "Password", cfg.get("password"))
			_hr(t)
			a = _q_select(
				"Action",
				[
					q.Choice(title="Start server", value="start"),
					q.Choice(title="Stop server", value="stop"),
					q.Choice(title="Change credentials", value="creds"),
					q.Choice(title="Back", value="back"),
				],
			)
			if a == "start":
				if running:
					click.echo(click.style("Already running", fg=t["warn"]))
				else:
					pid = fs_start(root_dir, str(cfg.get("host")), int(cfg.get("port")), str(cfg.get("user")), str(cfg.get("password")))
					click.echo(click.style("FTP server started", fg=t["ok"]))
					_kv(t, "Host", cfg.get("host"))
					_kv(t, "Port", cfg.get("port"))
					_kv(t, "Username", cfg.get("user"))
					_kv(t, "Password", cfg.get("password"))
					_kv(t, "PID", pid)
			elif a == "stop":
				if not running:
					click.echo(click.style("Not running", fg=t["warn"]))
				else:
					if fs_stop(root_dir):
						click.echo(click.style("FTP server stopped", fg=t["ok"]))
					else:
						click.echo(click.style("Failed to stop server", fg=t["err"]))
			elif a == "creds":
				new_host = _q_text("Host", default=str(cfg.get("host")))
				new_port = _q_text("Port", default=str(cfg.get("port")))
				new_user = _q_text("Username", default=str(cfg.get("user")))
				new_pass = _q_text("Password", default=str(cfg.get("password")))
				from .fileserver import write_config as fs_write
				fs_write(root_dir, {"host": new_host, "port": int(new_port), "user": new_user, "password": new_pass})
				click.echo(click.style("Updated credentials", fg=t["ok"]))
				_q_select("Continue", [q.Choice(title="Back", value="back")])
		elif main_choice == "open_root":
			_open_path(str(get_containers_dir(root_dir)))
		elif main_choice == "about":
			click.clear()
			_heading(t, "About")
			_kv(t, "Containify", "Local/Docker container manager")
			_kv(t, "Root", str(get_containers_dir(root_dir)))
			_kv(t, "Version", "0.1.0")
			_q_select("Continue", [q.Choice(title="Back", value="back")])
		elif main_choice == "settings":
			click.clear()
			_heading(t, "Settings")
			cur = read_settings(root_dir)
			colors = cur.get("theme", {}).get("colors", {})
			_kv(t, "Theme", cur.get("theme", {}).get("name"))
			_heading(t, "Theme Colors")
			for k in ["hr","heading","label","value","index","prompt","ok","warn","err"]:
				_kv(t, k, colors.get(k))
			_heading(t, "Defaults")
			defs = cur.get("defaults", {})
			_kv(t, "backend", defs.get("backend"))
			_kv(t, "ram_mb", defs.get("ram_mb"))
			_kv(t, "storage_mb", defs.get("storage_mb"))
			_kv(t, "cpu_percent", defs.get("cpu_percent"))
			_hr(t)
			act = _q_select(
				"Action",
				[
					q.Choice(title="Change theme colors", value="colors"),
					q.Choice(title="Change defaults", value="defaults"),
					q.Choice(title="Back", value="back"),
				],
			)
			if act == "colors":
				new = {}
				for k in ["hr","heading","label","value","index","prompt","ok","warn","err"]:
					new[k] = _q_text(k, default=str(colors.get(k)))
				cur["theme"]["colors"] = new
				write_settings(root_dir, cur)
				click.echo(click.style("Theme updated", fg=t["ok"]))
				_q_select("Continue", [q.Choice(title="Back", value="back")])
			elif act == "defaults":
				defs = {
					"backend": _q_select("backend", [q.Choice("local"), q.Choice("docker")], default=str(cur.get("defaults", {}).get("backend"))),
					"ram_mb": int(_q_text("ram_mb", default=str(cur.get("defaults", {}).get("ram_mb")))),
					"storage_mb": int(_q_text("storage_mb", default=str(cur.get("defaults", {}).get("storage_mb")))),
					"cpu_percent": int(_q_text("cpu_percent", default=str(cur.get("defaults", {}).get("cpu_percent")))),
				}
				cur["defaults"] = defs
				write_settings(root_dir, cur)
				click.echo(click.style("Defaults updated", fg=t["ok"]))
				_q_select("Continue", [q.Choice(title="Back", value="back")])
		else:
			break


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=2121, type=int, show_default=True)
@click.option("--user", default="containify", show_default=True)
@click.option("--password", default="containify", show_default=True)
@click.pass_context
def fileserver(ctx: click.Context, host: str, port: int, user: str, password: str):
	"""Manage the background FTP server (start if not running)."""
	root_dir = ctx.obj["root"]
	running, pid = fs_is_running(root_dir)
	if running:
		click.echo(click.style(f"FTP already running (PID {pid})", fg="yellow"))
		cfg = fs_read_config(root_dir)
		t = _theme(read_settings(root_dir)["theme"]["colors"])
		_kv(t, "Host", cfg.get("host"))
		_kv(t, "Port", cfg.get("port"))
		_kv(t, "Username", cfg.get("user"))
		_kv(t, "Password", cfg.get("password"))
		return
	pid = fs_start(root_dir, host, port, user, password)
	t = _theme(read_settings(root_dir)["theme"]["colors"])
	click.echo(click.style("FTP server started in background", fg=t["ok"]))
	_kv(t, "Host", host)
	_kv(t, "Port", port)
	_kv(t, "Username", user)
	_kv(t, "Password", password)
	_kv(t, "PID", pid)


@cli.command(hidden=True, name="fileserver-serve")
@click.option("--root", "root_override", type=click.Path(path_type=str), required=False)
@click.option("--host", default="127.0.0.1")
@click.option("--port", default=2121, type=int)
@click.option("--user", default="containify")
@click.option("--password", default="containify")
@click.pass_context
def fileserver_serve(ctx: click.Context, root_override: Optional[str], host: str, port: int, user: str, password: str):
	"""Internal: run the FTP server in foreground (spawned as detached)."""
	root_dir = get_root_dir(root_override)
	base_dir = str(get_containers_dir(root_dir))
	try:
		fs_serve(base_dir, host, port, user, password)
	except Exception as e:
		click.echo(click.style(f"FTP server error: {e}", fg="red"))


@cli.command()
@click.argument("name", type=str)
@click.option("--backend", type=click.Choice(["local", "docker"]), default="local", show_default=True)
@click.option("--ram", type=str, default="0", help="RAM in MB or like 512m, 2g (0 to skip)")
@click.option("--storage", type=str, default="0", help="Storage in MB or like 1g (best-effort for local)")
@click.option("--cpu", type=int, default=100, help="Max CPU percent (1-100)")
@click.pass_context
def create(ctx: click.Context, name: str, backend: str, ram: str, storage: str, cpu: int):
	"""Create a new container with limits and workspace."""
	validate_container_name(name)
	root_dir = ctx.obj["root"]
	resources = get_system_resources(root_dir)
	mem_mb = parse_size_to_mb(ram)
	storage_mb = parse_size_to_mb(storage)
	cpu_percent = max(1, min(100, int(cpu)))
	limits = {"memory_mb": mem_mb, "storage_mb": storage_mb, "cpu_percent": cpu_percent}
	if backend == "local":
		md = create_local_container(name, root_dir, limits)
	else:
		md = create_docker_container(name, root_dir, limits)
	click.echo(json.dumps({"created": md, "system": resources}, indent=2))


@cli.command(name="list")
@click.pass_context
def list_cmd(ctx: click.Context):
	"""List containers."""
	root_dir = ctx.obj["root"]
	items = list_local_containers(root_dir) + list_docker_containers(root_dir)
	click.echo(json.dumps(items, indent=2))


@cli.command()
@click.argument("name", type=str)
@click.pass_context
def info(ctx: click.Context, name: str):
	"""Show container info."""
	root_dir = ctx.obj["root"]
	md = None
	try:
		md = read_local_metadata(name, root_dir)
	except Exception:
		pass
	if md is None:
		try:
			md = read_docker_metadata(name, root_dir)
		except Exception:
			pass
	if md is None:
		raise click.UsageError(f"Container '{name}' not found")
	click.echo(json.dumps(md, indent=2))


@cli.command()
@click.argument("name", type=str)
@click.option("--", "--", help="Pass following args as command", flag_value=True, expose_value=False)
@click.argument("command", nargs=-1, type=str)
@click.pass_context
def run(ctx: click.Context, name: str, command: tuple[str, ...]):
	"""Run a command inside the container workspace/env."""
	root_dir = ctx.obj["root"]
	if not command:
		raise click.UsageError("Provide a command to run")
	backend = _resolve_backend(name, root_dir)
	if backend == "local":
		code = run_in_local(name, root_dir, list(command))
		click.get_current_context().exit(code)
		return
	if backend == "docker":
		code = run_in_docker(name, root_dir, list(command))
		click.get_current_context().exit(code)
		return
	raise click.UsageError(f"Container '{name}' not found")


@cli.command()
@click.argument("name", type=str)
@click.pass_context
def shell(ctx: click.Context, name: str):
	"""Open an interactive shell inside the container."""
	root_dir = ctx.obj["root"]
	backend = _resolve_backend(name, root_dir)
	if backend == "local":
		code = shell_in_local(name, root_dir)
		click.get_current_context().exit(code)
		return
	if backend == "docker":
		code = shell_in_docker(name, root_dir)
		click.get_current_context().exit(code)
		return
	raise click.UsageError(f"Container '{name}' not found")


@cli.command()
@click.argument("name", type=str)
@click.argument("packages", nargs=-1, type=str)
@click.pass_context
def install(ctx: click.Context, name: str, packages: tuple[str, ...]):
	"""Install Python packages into the container."""
	root_dir = ctx.obj["root"]
	backend = _resolve_backend(name, root_dir)
	if backend == "local":
		code = install_in_local(name, root_dir, list(packages))
		click.get_current_context().exit(code)
		return
	if backend == "docker":
		code = install_in_docker(name, root_dir, list(packages))
		click.get_current_context().exit(code)
		return
	raise click.UsageError(f"Container '{name}' not found")


@cli.command()
@click.argument("name", type=str, required=False)
@click.option("--yes", is_flag=True, help="Confirm deletion without prompt (for single container)")
@click.pass_context
def delete(ctx: click.Context, name: Optional[str], yes: bool):
	"""Delete a container by name, or run full uninstall if no name is provided."""
	root_dir = ctx.obj["root"]
	if name:
		# Single container deletion (existing behavior)
		if not yes and not click.confirm(f"Delete container '{name}'? This cannot be undone."):
			return
		backend = _resolve_backend(name, root_dir)
		if backend == "local":
			delete_local_container(name, root_dir)
			click.echo(f"Deleted local '{name}'")
			return
		if backend == "docker":
			delete_docker_container(name, root_dir)
			click.echo(f"Deleted docker '{name}'")
			return
		raise click.ClickException(f"Container '{name}' not found")

	# Interactive full uninstall flow
	settings = read_settings(root_dir)
	t = _theme(settings.get("theme", {}).get("colors", {}))
	click.clear()
	_heading(t, "Uninstall / Cleanup")
	_kv(t, "Root", str(get_containers_dir(root_dir)))
	choice = _q_select(
		"Select action",
		[
			q.Choice(title="Remove ALL containers and data", value="data"),
			q.Choice(title="Uninstall Containify CLI (pip uninstall)", value="pip"),
			q.Choice(title="Remove Containify source code folder", value="code"),
			q.Choice(title="Full uninstall (all of the above)", value="all"),
			q.Choice(title="Back", value="back"),
		],
	)
	if choice == "back":
		return

	do_data = choice in ("data", "all")
	do_pip = choice in ("pip", "all")
	do_code = choice in ("code", "all")

	# Confirm
	summary = []
	if do_data:
		summary.append("- Remove containers, settings, FTP config")
	if do_pip:
		summary.append("- pip uninstall containify")
	if do_code:
		summary.append("- Delete Containify code directory")
	if not _q_confirm("Proceed with:\n" + "\n".join(summary), default=False):
		return

	import os, shutil, sys, tempfile, textwrap, psutil
	ops_ok = True

	# 1) Data cleanup
	if do_data:
		try:
			# Delete containers dir and settings files under root
			containers_path = get_containers_dir(root_dir)
			shutil.rmtree(containers_path, ignore_errors=True)
			for fname in ("settings.json", "fileserver.json", "fileserver.pid"):
				try:
					(os.path.join(root_dir, fname) if isinstance(root_dir, str) else str(root_dir / fname))
				except Exception:
					pass
			# Also try deleting the root itself if empty
			try:
				(os.rmdir(root_dir))
			except Exception:
				pass
			click.echo(click.style("Data removed", fg=t["ok"]))
		except Exception as e:
			ops_ok = False
			click.echo(click.style(f"Data removal failed: {e}", fg=t["err"]))

	# 2) Determine code directory
	code_dir = None
	try:
		import containify as _pkg
		from pathlib import Path as _Path
		pkg_file = _Path(_pkg.__file__).resolve()
		# Search upwards for pyproject.toml to identify project root (editable installs)
		cur = pkg_file
		for _ in range(6):
			if (cur.parent / "pyproject.toml").exists():
				code_dir = str(cur.parent)
				break
			cur = cur.parent
		# If not found, assume site-packages package directory
		if code_dir is None:
			code_dir = str(pkg_file.parent)
	except Exception:
		pass

	# 3) pip uninstall
	if do_pip:
		try:
			import subprocess
			subprocess.call([sys.executable, "-m", "pip", "uninstall", "-y", "containify"])  # best-effort
			click.echo(click.style("CLI uninstalled", fg=t["ok"]))
		except Exception as e:
			ops_ok = False
			click.echo(click.style(f"pip uninstall failed: {e}", fg=t["err"]))

	# 4) Code deletion
	if do_code and code_dir:
		# If we are running from inside code_dir on Windows, deleting in-process may fail.
		# Use a detached helper to delete after exit.
		try:
			helper = tempfile.NamedTemporaryFile(delete=False, suffix="_containify_purge.py")
			helper_path = helper.name
			helper.write(textwrap.dedent(f"""
			import os, shutil, sys, time
			paths = { [repr(code_dir)] }
			time.sleep(0.8)
			for p in paths:
				try:
					shutil.rmtree(p, ignore_errors=True)
				except Exception:
					pass
			try:
				os.remove(__file__)
			except Exception:
				pass
			""").encode("utf-8"))
			helper.close()
			creationflags = 0
			kwargs = {}
			if os.name == "nt":
				creationflags = 0x00000008 | 0x00000200 | 0x08000000
				kwargs["creationflags"] = creationflags
			psutil.Popen([sys.executable, helper_path], close_fds=True, **kwargs)
			click.echo(click.style(f"Code removal scheduled: {code_dir}", fg=t["ok"]))
		except Exception as e:
			# Try inline as fallback
			try:
				shutil.rmtree(code_dir, ignore_errors=True)
				click.echo(click.style(f"Code removed: {code_dir}", fg=t["ok"]))
			except Exception as e2:
				ops_ok = False
				click.echo(click.style(f"Code removal failed: {e2}", fg=t["err"]))

	if ops_ok:
		click.echo(click.style("Done.", fg=t["ok"]))
	else:
		click.echo(click.style("Completed with some errors.", fg=t["warn"]))


def main() -> None:
	cli(auto_envvar_prefix="CONTAINIFY")
