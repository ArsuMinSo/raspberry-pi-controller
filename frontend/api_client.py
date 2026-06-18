import requests


class ApiError(Exception):
    pass


class ApiClient:
    def __init__(self, base_url: str):
        self._base = base_url.rstrip("/")
        self._session = requests.Session()

    def _get(self, path: str, params: dict | None = None):
        try:
            r = self._session.get(
                f"{self._base}{path}",
                params={k: v for k, v in (params or {}).items() if v is not None},
                timeout=30,
            )
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            raise ApiError(detail)
        except requests.RequestException as e:
            raise ApiError(str(e))

    def _patch(self, path: str, data: dict):
        try:
            r = self._session.patch(f"{self._base}{path}", json=data, timeout=30)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            raise ApiError(detail)
        except requests.RequestException as e:
            raise ApiError(str(e))

    def _post(self, path: str, data: dict):
        try:
            r = self._session.post(f"{self._base}{path}", json=data, timeout=60)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            try:
                detail = e.response.json().get("detail", str(e))
            except Exception:
                detail = str(e)
            raise ApiError(detail)
        except requests.RequestException as e:
            raise ApiError(str(e))

    def system_health(self) -> dict:
        return self._get("/health")

    def create_pi(self, position: str, mac: str = "00:00:00:00:00:00",
                  hostname: str | None = None, ip: str | None = None,
                  pi_version: int | None = None, tags: list[str] | None = None,
                  status: str = "unreachable") -> dict:
        return self._post("/pi", {
            "position": position, "mac": mac, "hostname": hostname,
            "ip": ip, "pi_version": pi_version, "tags": tags or [], "status": status,
        })

    def update_pi(self, position: str, **fields) -> dict:
        return self._patch(f"/pi/{position}", {k: v for k, v in fields.items() if v is not None})

    def deploy_key(self, positions: list[str], password: str) -> dict:
        return self._post("/pi/deploy-key", {"pis": positions, "password": password})

    def delete_pi(self, position: str) -> None:
        try:
            self._session.delete(f"{self._base}/pi/{position}", timeout=30).raise_for_status()
        except Exception as e:
            raise ApiError(str(e))

    def list_pis(self, status: str | None = None, tags: list[str] | None = None) -> list[dict]:
        params: dict = {"limit": 500}
        if status:
            params["status"] = status
        if tags:
            params["tags"] = tags
        return self._get("/pi/list", params)

    def execute_command(self, positions: list[str], command: str) -> dict:
        return self._post("/command/execute", {"pis": positions, "command": command})

    def get_command_result(self, action_id: int) -> dict:
        return self._get(f"/command/{action_id}")

    def kill_process(self, positions: list[str], process_name: str, signal: str = "SIGTERM") -> dict:
        return self._post("/process/kill", {
            "pis": positions,
            "process_name": process_name,
            "signal": signal,
        })

    def get_process_result(self, action_id: int) -> dict:
        return self._get(f"/command/{action_id}")

    def restart_service(self, positions: list[str], service: str) -> dict:
        return self._post("/service/restart", {"pis": positions, "service": service})

    def trigger_health(self, positions: list[str] | None = None, all_pis: bool = False) -> dict:
        body = {"all": True} if all_pis else {"pis": positions or []}
        return self._post("/health/trigger", body)

    def get_health_result(self, action_id: int) -> dict:
        return self._get(f"/health/{action_id}")

    def get_logs(self, pi: str | None = None, limit: int = 100) -> list[dict]:
        params: dict = {"limit": limit}
        if pi:
            params["pi"] = pi
        return self._get("/logs", params)

    def scan_discovery(self) -> dict:
        return self._post("/discovery/scan", {})

    def get_discovery_result(self, action_id: int) -> dict:
        return self._get(f"/discovery/scan/{action_id}")

    def get_settings(self) -> dict:
        return self._get("/settings")

    def update_ssh_settings(
        self,
        key_path: str | None = None,
        username: str | None = None,
        timeout_s: int | None = None,
    ) -> dict:
        body = {}
        if key_path is not None:
            body["ssh_key_path"] = key_path
        if username is not None:
            body["username"] = username
        if timeout_s is not None:
            body["timeout_s"] = timeout_s
        return self._patch("/settings", body)

    def update_network_settings(self, subnet: str, probe_ssh: bool | None = None) -> dict:
        body: dict = {"subnet": subnet}
        if probe_ssh is not None:
            body["probe_ssh"] = probe_ssh
        return self._patch("/settings", body)

    def test_ssh_connection(self, ip: str) -> dict:
        return self._post("/settings/test", {"ip": ip})
