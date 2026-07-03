# Modbus B2B Service

Small Python service with two Modbus TCP slave endpoints that share the same holding-register bank.

Default register bank:

- Holding registers: `40000` to `41000`
- Active/debug range: `40033` to `40359`
- Side A: `0.0.0.0:502`
- Side B: `0.0.0.0:1502`
- Debug UI: `http://127.0.0.1:8080`

## Install

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

If `py -3` is not available, use the Python executable installed on the machine.

## Run

```powershell
.\.venv\Scripts\python .\modbus_b2b_service.py --config .\config.example.json
```

Port `502` may require administrator rights, depending on OS and deployment policy.

For a quick non-privileged smoke test:

```powershell
.\.venv\Scripts\python .\smoke_test.py
```

## Two standard Modbus TCP ports

Two services cannot listen on the same IP and same port. If both sides must use port `502`, bind them to different local IP addresses:

```json
{
  "side_a": { "host": "192.168.1.10", "port": 502 },
  "side_b": { "host": "192.168.2.10", "port": 502 }
}
```

## Address mapping

The debug UI always shows the human register numbers, for example `40033`.

`modbus_base` controls how Modbus PDU addresses map to those numbers:

- `40000`: PDU address `33` maps to register `40033`
- `40001`: PDU address `32` maps to register `40033`

If a client reads the wrong register by one, change `modbus_base` in `config.example.json`.

## Unit ID

`single_unit` is `true` by default, which means the server accepts the Modbus TCP Unit ID sent by the client and uses the same shared bank. Set it to `false` to require the configured `unit_id`.

## Register names

Put known register definitions in `registers.example.json`:

```json
{
  "40033": {
    "name": "Pump status",
    "description": "0=Stopped, 1=Running"
  }
}
```

The file can be renamed; update `registers.definitions_file` in the config.

## Windows service option

## Build EXE

Build a remote-install package:

```powershell
.\build-exe.ps1
```

Output:

- `release\ModbusB2B\ModbusB2B.exe`
- `release\ModbusB2B\config.json`
- `release\ModbusB2B\registers.json`
- `release\ModbusB2B.zip`

## Auto-start install on remote Windows machine

Copy `release\ModbusB2B.zip` to the remote machine, unzip it, then run elevated PowerShell from the unzipped folder:

```powershell
.\install-autostart.ps1 -StartNow
```

This installs the EXE to `C:\Program Files\ModbusB2B` and registers a startup task named `ModbusB2B` running as `SYSTEM`. Logs are written to `C:\Program Files\ModbusB2B\logs\service.log`.

Uninstall:

```powershell
.\uninstall-autostart.ps1
```

Remove installed files too:

```powershell
.\uninstall-autostart.ps1 -RemoveFiles
```
