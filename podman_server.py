"""Podman/Docker container management MCP Server."""
import subprocess
import json
from .base import BaseMCPServer


class PodmanServer(BaseMCPServer):
    def __init__(self, socket_path: str = None):
        self.socket_path = socket_path
        # Detect podman or docker
        self.cmd = self._detect_runtime()

    def _detect_runtime(self) -> str:
        for runtime in ("podman", "docker"):
            try:
                subprocess.run([runtime, "--version"], capture_output=True, timeout=3)
                return runtime
            except (FileNotFoundError, subprocess.TimeoutExpired):
                continue
        return "docker"  # fallback default

    def _run(self, *args) -> dict:
        try:
            result = subprocess.run(
                [self.cmd] + list(args),
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return {"error": result.stderr.strip() or f"{self.cmd} command failed"}
            return {"output": result.stdout.strip()}
        except FileNotFoundError:
            return {"error": f"{self.cmd} not installed"}
        except subprocess.TimeoutExpired:
            return {"error": "Command timed out"}

    def _run_json(self, *args) -> list:
        result = self._run(*args, "--format", "json")
        if "error" in result:
            return []
        try:
            return json.loads(result["output"])
        except Exception:
            return []

    def list_containers(self, all: bool = True) -> dict:
        args = ["ps", "--format", "json"]
        if all:
            args.append("-a")
        result = self._run(*args)
        if "error" in result:
            return result
        try:
            containers = json.loads(result["output"]) if result["output"] else []
            return {"containers": containers, "count": len(containers)}
        except Exception:
            return {"containers": [], "raw": result["output"]}

    def list_images(self) -> dict:
        result = self._run("images", "--format", "json")
        if "error" in result:
            return result
        try:
            images = json.loads(result["output"]) if result["output"] else []
            return {"images": images, "count": len(images)}
        except Exception:
            return {"images": [], "raw": result["output"]}

    def run_container(self, image: str, name: str = None, ports: dict = None,
                      volumes: dict = None, env: dict = None, detach: bool = True) -> dict:
        args = ["run"]
        if detach:
            args.append("-d")
        if name:
            args += ["--name", name]
        for host, container in (ports or {}).items():
            args += ["-p", f"{host}:{container}"]
        for host, container in (volumes or {}).items():
            args += ["-v", f"{host}:{container}"]
        for k, v in (env or {}).items():
            args += ["-e", f"{k}={v}"]
        args.append(image)
        return self._run(*args)

    def stop_container(self, container: str) -> dict:
        return self._run("stop", container)

    def start_container(self, container: str) -> dict:
        return self._run("start", container)

    def remove_container(self, container: str, force: bool = False) -> dict:
        args = ["rm", container]
        if force:
            args.insert(1, "-f")
        return self._run(*args)

    def container_logs(self, container: str, tail: int = 100) -> dict:
        return self._run("logs", "--tail", str(tail), container)

    def exec_in_container(self, container: str, command: str) -> dict:
        import shlex
        return self._run("exec", container, *shlex.split(command))

    def pull_image(self, image: str, tag: str = "latest") -> dict:
        img = f"{image}:{tag}" if ":" not in image else image
        return self._run("pull", img)

    def system_info(self) -> dict:
        return self._run("info", "--format", "json")
