import shutil
from pathlib import Path
from typing import Dict

import psutil


def get_system_resources(root_path: Path) -> Dict[str, int]:
	vm = psutil.virtual_memory()
	cpu_logical = psutil.cpu_count(logical=True) or 1
	cpu_physical = psutil.cpu_count(logical=False) or cpu_logical
	# Disk stats for the drive containing root_path
	total, used, free = shutil.disk_usage(str(root_path))
	return {
		"total_ram_mb": int(vm.total / (1024 * 1024)),
		"available_ram_mb": int(vm.available / (1024 * 1024)),
		"cpu_count_logical": int(cpu_logical),
		"cpu_count_physical": int(cpu_physical),
		"disk_total_gb": int(total / (1024 * 1024 * 1024)),
		"disk_free_gb": int(free / (1024 * 1024 * 1024)),
	}
