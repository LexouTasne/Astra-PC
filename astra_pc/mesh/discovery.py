from __future__ import annotations

import socket
from typing import Any

SERVICE_TYPE = "_astra-mesh._tcp.local."


class MeshDiscovery:
    def __init__(
        self,
        *,
        name: str,
        port: int,
        node_id: str,
        fingerprint: str,
        version: str = "0.8",
    ):
        self.name = name
        self.port = port
        self.node_id = node_id
        self.fingerprint = fingerprint
        self.version = version
        self._zc = None
        self._info = None

    def start(self) -> bool:
        try:
            from zeroconf import ServiceInfo, Zeroconf
        except ImportError:
            return False

        try:
            address = socket.inet_aton(self._local_ip())
            properties = {
                b"node_id": self.node_id.encode(),
                b"fingerprint": self.fingerprint.encode(),
                b"version": self.version.encode(),
                b"tls": b"1",
            }
            info = ServiceInfo(
                SERVICE_TYPE,
                f"{self.name}.{SERVICE_TYPE}",
                addresses=[address],
                port=self.port,
                properties=properties,
                server=f"{socket.gethostname()}.local.",
            )
            zc = Zeroconf()
            zc.register_service(info)
            self._zc = zc
            self._info = info
            return True
        except Exception:
            self.stop()
            return False

    def stop(self) -> None:
        try:
            if self._zc and self._info:
                self._zc.unregister_service(self._info)
        except Exception:
            pass
        try:
            if self._zc:
                self._zc.close()
        except Exception:
            pass
        self._zc = self._info = None

    @staticmethod
    def _local_ip() -> str:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("1.1.1.1", 80))
            return str(sock.getsockname()[0])
        except Exception:
            return "127.0.0.1"
        finally:
            sock.close()


def discover(timeout_ms: int = 1800) -> list[dict[str, Any]]:
    try:
        from zeroconf import ServiceBrowser, ServiceListener, Zeroconf
    except ImportError:
        return []

    import time

    results: dict[str, dict] = {}

    class Listener(ServiceListener):
        def add_service(self, zc, service_type, name):
            info = zc.get_service_info(service_type, name, timeout=700)
            if not info:
                return
            props = {
                k.decode(errors="ignore"): v.decode(errors="ignore")
                for k, v in info.properties.items()
            }
            addrs = info.parsed_addresses()
            results[name] = {
                "name": name.removesuffix("." + SERVICE_TYPE),
                "host": addrs[0] if addrs else "",
                "port": info.port,
                **props,
            }

        def update_service(self, zc, service_type, name):
            self.add_service(zc, service_type, name)

        def remove_service(self, zc, service_type, name):
            pass

    zc = Zeroconf()
    try:
        ServiceBrowser(zc, SERVICE_TYPE, Listener())
        time.sleep(max(0.2, timeout_ms / 1000.0))
        return list(results.values())
    finally:
        zc.close()
