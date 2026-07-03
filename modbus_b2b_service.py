#!/usr/bin/env python3
"""Two Modbus TCP slave endpoints sharing one holding-register bank."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import threading
from dataclasses import dataclass, field
from functools import partial
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from pymodbus.constants import ExcCodes
from pymodbus.server import StartAsyncTcpServer
from pymodbus.simulator import SimData, SimDevice
from pymodbus.simulator.simutils import DataType


LOG = logging.getLogger("modbus-b2b")


DEFAULT_CONFIG: dict[str, Any] = {
    "side_a": {"name": "Citect side", "host": "0.0.0.0", "port": 502},
    "side_b": {"name": "Upstream side", "host": "0.0.0.0", "port": 1502},
    "debug": {"host": "127.0.0.1", "port": 8080},
    "registers": {
        "start": 40000,
        "end": 41000,
        "active_start": 40033,
        "active_end": 40359,
        "modbus_base": 40000,
        "definitions_file": "registers.example.json",
    },
    "unit_id": 1,
    "single_unit": True,
}


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return DEFAULT_CONFIG
    with path.open("r", encoding="utf-8") as handle:
        return deep_merge(DEFAULT_CONFIG, json.load(handle))


def load_definitions(path: str | None, config_dir: Path) -> dict[int, dict[str, Any]]:
    if not path:
        return {}
    definition_path = Path(path)
    if not definition_path.is_absolute():
        definition_path = config_dir / definition_path
    if not definition_path.exists():
        LOG.warning("Register definitions file not found: %s", definition_path)
        return {}
    with definition_path.open("r", encoding="utf-8") as handle:
        raw = json.load(handle)
    return {int(register): details for register, details in raw.items()}


def normalize_bind_host(host: str) -> str:
    normalized = host.strip().lower()
    if normalized == "localhost":
        return "127.0.0.1"
    return normalized


def bind_endpoints_conflict(left_host: str, left_port: int, right_host: str, right_port: int) -> bool:
    if left_port != right_port:
        return False
    left = normalize_bind_host(left_host)
    right = normalize_bind_host(right_host)
    if left == right:
        return True
    return "0.0.0.0" in {left, right}


def validate_listener_config(config: dict[str, Any]) -> None:
    listeners = [
        ("side_a", str(config["side_a"]["host"]), int(config["side_a"]["port"])),
        ("side_b", str(config["side_b"]["host"]), int(config["side_b"]["port"])),
        ("debug", str(config["debug"]["host"]), int(config["debug"]["port"])),
    ]
    for index, left in enumerate(listeners):
        for right in listeners[index + 1 :]:
            if bind_endpoints_conflict(left[1], left[2], right[1], right[2]):
                raise ValueError(
                    f"{left[0]} ({left[1]}:{left[2]}) conflicts with "
                    f"{right[0]} ({right[1]}:{right[2]}). Use different ports, "
                    "different concrete IP addresses, or avoid 0.0.0.0 on the same port."
                )


@dataclass
class RegisterBank:
    start: int
    end: int
    active_start: int
    active_end: int
    modbus_base: int
    definitions: dict[int, dict[str, Any]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.end < self.start:
            raise ValueError("register end must be greater than or equal to start")
        self._values = [0] * (self.end - self.start + 1)
        self._lock = threading.RLock()

    def pdu_to_register(self, address: int) -> int:
        return self.modbus_base + address

    def register_to_pdu(self, register: int) -> int:
        return register - self.modbus_base

    def validate_register_range(self, register: int, count: int = 1) -> bool:
        return self.start <= register and register + count - 1 <= self.end

    def get_values(self, register: int, count: int) -> list[int]:
        if count < 1:
            return []
        if not self.validate_register_range(register, count):
            raise IndexError(f"register range outside bank: {register} count={count}")
        offset = register - self.start
        with self._lock:
            return list(self._values[offset : offset + count])

    def set_values(self, register: int, values: list[int]) -> None:
        if not values:
            return
        if not self.validate_register_range(register, len(values)):
            raise IndexError(f"register range outside bank: {register} count={len(values)}")
        cleaned = [int(value) & 0xFFFF for value in values]
        offset = register - self.start
        with self._lock:
            self._values[offset : offset + len(cleaned)] = cleaned

    def snapshot(self, start: int | None = None, count: int | None = None, changed_only: bool = False) -> list[dict[str, Any]]:
        view_start = self.active_start if start is None else start
        if count is None:
            view_end = self.active_end
        else:
            view_end = min(self.end, view_start + max(0, count) - 1)
        view_start = max(self.start, view_start)
        view_end = min(self.end, view_end)

        rows = []
        with self._lock:
            for register in range(view_start, view_end + 1):
                value = self._values[register - self.start]
                if changed_only and value == 0 and register not in self.definitions:
                    continue
                definition = self.definitions.get(register, {})
                rows.append(
                    {
                        "register": register,
                        "pdu_address": self.register_to_pdu(register),
                        "value": value,
                        "name": definition.get("name", ""),
                        "description": definition.get("description", ""),
                    }
                )
        return rows


HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Modbus B2B Debug</title>
  <style>
    :root { color-scheme: light dark; font-family: Arial, sans-serif; }
    body { margin: 24px; background: #f6f7f9; color: #18202a; }
    header { display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }
    h1 { font-size: 22px; margin: 0 20px 0 0; }
    label { font-size: 13px; display: inline-flex; gap: 6px; align-items: center; }
    input, button { font: inherit; padding: 7px 9px; border: 1px solid #b9c1cc; border-radius: 6px; }
    button { background: #1f6feb; color: white; border-color: #1f6feb; cursor: pointer; }
    table { width: 100%; border-collapse: collapse; margin-top: 18px; background: white; }
    th, td { border-bottom: 1px solid #dde2e8; padding: 7px 9px; text-align: left; }
    th { position: sticky; top: 0; background: #edf1f5; font-size: 12px; text-transform: uppercase; }
    td input { width: 96px; }
    .status { margin-top: 12px; font-size: 13px; color: #53606f; }
    .desc { color: #53606f; font-size: 13px; }
    @media (prefers-color-scheme: dark) {
      body { background: #12161d; color: #e7ebf0; }
      table { background: #1a2029; }
      th { background: #232b36; }
      th, td { border-bottom-color: #303947; }
      input { background: #151b23; color: #e7ebf0; border-color: #3d4654; }
      .status, .desc { color: #aab4c0; }
    }
  </style>
</head>
<body>
  <header>
    <h1>Modbus B2B Debug</h1>
    <label>Start <input id="start" type="number"></label>
    <label>Count <input id="count" type="number" min="1" max="1001" value="80"></label>
    <label><input id="changed" type="checkbox"> Changed/defined only</label>
    <button onclick="loadRows()">Refresh</button>
  </header>
  <div class="status" id="status"></div>
  <table>
    <thead><tr><th>Register</th><th>PDU</th><th>Value</th><th>Name</th><th>Description</th><th></th></tr></thead>
    <tbody id="rows"></tbody>
  </table>
<script>
async function loadRows() {
  const params = new URLSearchParams({
    start: document.getElementById('start').value,
    count: document.getElementById('count').value,
    changed: document.getElementById('changed').checked ? '1' : '0'
  });
  const res = await fetch('/api/registers?' + params.toString());
  const data = await res.json();
  document.getElementById('start').value = data.start;
  document.getElementById('status').textContent =
    `Bank ${data.bank_start}-${data.bank_end}, active ${data.active_start}-${data.active_end}, modbus_base ${data.modbus_base}`;
  document.getElementById('rows').innerHTML = data.rows.map(row => `
    <tr>
      <td>${row.register}</td>
      <td>${row.pdu_address}</td>
      <td><input id="v${row.register}" type="number" min="0" max="65535" value="${row.value}"></td>
      <td>${escapeHtml(row.name)}</td>
      <td class="desc">${escapeHtml(row.description)}</td>
      <td><button onclick="writeRegister(${row.register})">Write</button></td>
    </tr>`).join('');
}
async function writeRegister(register) {
  const value = Number(document.getElementById('v' + register).value);
  const res = await fetch('/api/registers', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({register, value})
  });
  if (!res.ok) alert(await res.text());
  await loadRows();
}
function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
loadRows();
setInterval(loadRows, 3000);
</script>
</body>
</html>
"""


class DebugServer(ThreadingHTTPServer):
    def __init__(self, address: tuple[str, int], bank: RegisterBank) -> None:
        super().__init__(address, DebugHandler)
        self.bank = bank


class DebugHandler(BaseHTTPRequestHandler):
    server: DebugServer

    def log_message(self, format: str, *args: Any) -> None:
        LOG.info("debug %s - %s", self.address_string(), format % args)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str, status: HTTPStatus = HTTPStatus.OK, content_type: str = "text/plain") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._send_text(HTML, content_type="text/html")
            return
        if parsed.path == "/api/registers":
            params = parse_qs(parsed.query)
            bank = self.server.bank
            start = int(params.get("start", [bank.active_start])[0] or bank.active_start)
            count = int(params.get("count", [bank.active_end - bank.active_start + 1])[0] or 80)
            changed = params.get("changed", ["0"])[0] == "1"
            self._send_json(
                {
                    "bank_start": bank.start,
                    "bank_end": bank.end,
                    "active_start": bank.active_start,
                    "active_end": bank.active_end,
                    "modbus_base": bank.modbus_base,
                    "start": start,
                    "count": count,
                    "rows": bank.snapshot(start=start, count=count, changed_only=changed),
                }
            )
            return
        self._send_text("not found", HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if urlparse(self.path).path != "/api/registers":
            self._send_text("not found", HTTPStatus.NOT_FOUND)
            return
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        register = int(payload["register"])
        if "values" in payload:
            values = [int(value) for value in payload["values"]]
        else:
            values = [int(payload["value"])]
        try:
            self.server.bank.set_values(register, values)
        except (IndexError, ValueError) as exc:
            self._send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"ok": True, "register": register, "values": values})


def start_debug_server(bank: RegisterBank, host: str, port: int) -> DebugServer:
    server = DebugServer((host, port), bank)
    thread = threading.Thread(target=server.serve_forever, name="debug-http", daemon=True)
    thread.start()
    LOG.info("debug UI listening on http://%s:%s", host, port)
    return server


async def bank_action(
    bank: RegisterBank,
    func_code: int,
    start_address: int,
    address: int,
    count: int,
    current_registers: list[int],
    set_values: list[int] | list[bool] | None,
) -> None | ExcCodes:
    _ = func_code
    register = bank.pdu_to_register(address)
    offset = address - start_address
    try:
        if set_values is None:
            values = bank.get_values(register, count)
            current_registers[offset : offset + count] = values
            LOG.debug("read hr register=%s count=%s values=%s", register, count, values)
        else:
            values = [int(value) & 0xFFFF for value in set_values]
            bank.set_values(register, values)
            LOG.debug("write hr register=%s values=%s", register, values)
    except (IndexError, ValueError):
        return ExcCodes.ILLEGAL_ADDRESS
    return None


def make_device(bank: RegisterBank, unit_id: int, single_unit: bool) -> SimDevice:
    pdu_start = bank.register_to_pdu(bank.start)
    register_count = bank.end - bank.start + 1
    return SimDevice(
        id=0 if single_unit else unit_id,
        simdata=(
            [SimData(address=0, count=1, values=False, datatype=DataType.BITS)],
            [SimData(address=0, count=1, values=False, datatype=DataType.BITS, readonly=True)],
            [SimData(address=pdu_start, count=register_count, values=0, datatype=DataType.REGISTERS)],
            [SimData(address=0, count=1, values=0, datatype=DataType.REGISTERS, readonly=True)],
        ),
        action=partial(bank_action, bank),
    )


async def run_modbus_side(name: str, host: str, port: int, device: SimDevice) -> None:
    LOG.info("%s listening on %s:%s", name, host, port)
    await StartAsyncTcpServer(context=device, address=(host, port))


async def run(config: dict[str, Any], config_dir: Path) -> None:
    validate_listener_config(config)
    register_config = config["registers"]
    bank = RegisterBank(
        start=int(register_config["start"]),
        end=int(register_config["end"]),
        active_start=int(register_config["active_start"]),
        active_end=int(register_config["active_end"]),
        modbus_base=int(register_config["modbus_base"]),
        definitions=load_definitions(register_config.get("definitions_file"), config_dir),
    )
    LOG.info(
        "holding register bank %s-%s, active %s-%s, modbus_base=%s",
        bank.start,
        bank.end,
        bank.active_start,
        bank.active_end,
        bank.modbus_base,
    )

    device = make_device(bank, int(config["unit_id"]), bool(config["single_unit"]))
    debug_config = config["debug"]
    debug_server = start_debug_server(bank, str(debug_config["host"]), int(debug_config["port"]))

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            pass

    side_a = config["side_a"]
    side_b = config["side_b"]
    tasks = [
        asyncio.create_task(run_modbus_side(str(side_a["name"]), str(side_a["host"]), int(side_a["port"]), device)),
        asyncio.create_task(run_modbus_side(str(side_b["name"]), str(side_b["host"]), int(side_b["port"]), device)),
        asyncio.create_task(stop_event.wait()),
    ]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.exception():
                raise task.exception()
        for task in pending:
            task.cancel()
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        debug_server.shutdown()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Two Modbus TCP slave endpoints sharing holding registers.")
    parser.add_argument("--config", type=Path, help="Path to JSON config file")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-file", type=Path, help="Optional log file path")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(args.log_file, encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )
    config = load_config(args.config)
    config_dir = args.config.resolve().parent if args.config else Path.cwd()
    asyncio.run(run(config, config_dir))


if __name__ == "__main__":
    main()
