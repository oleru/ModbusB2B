#!/usr/bin/env python3
"""Start the service briefly on high ports to verify imports and binding."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

from pymodbus.client import ModbusTcpClient

import modbus_b2b_service as service


def verify_shared_register() -> int:
    write_client = ModbusTcpClient("127.0.0.1", port=15020)
    read_client = ModbusTcpClient("127.0.0.1", port=15021)
    try:
        if not write_client.connect():
            raise RuntimeError("could not connect to side A")
        if not read_client.connect():
            raise RuntimeError("could not connect to side B")
        write_result = write_client.write_register(33, 321, device_id=1)
        if write_result.isError():
            raise RuntimeError(f"write failed: {write_result}")
        read_result = read_client.read_holding_registers(33, count=1, device_id=1)
        if read_result.isError():
            raise RuntimeError(f"read failed: {read_result}")
        return int(read_result.registers[0])
    finally:
        write_client.close()
        read_client.close()


async def main() -> None:
    config = copy.deepcopy(service.DEFAULT_CONFIG)
    config["side_a"]["host"] = "127.0.0.1"
    config["side_a"]["port"] = 15020
    config["side_b"]["host"] = "127.0.0.1"
    config["side_b"]["port"] = 15021
    config["debug"]["host"] = "127.0.0.1"
    config["debug"]["port"] = 18080

    task = asyncio.create_task(service.run(config, Path(".")))
    await asyncio.sleep(1)
    print("started on 127.0.0.1:15020, 127.0.0.1:15021, debug 127.0.0.1:18080")
    value = await asyncio.to_thread(verify_shared_register)
    if value != 321:
        raise RuntimeError(f"expected shared register value 321, got {value}")
    print("shared holding register check ok: 40033=321")
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        print("stopped")


if __name__ == "__main__":
    asyncio.run(main())
