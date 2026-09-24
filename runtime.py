"""CUPS adapter: an incoming document creates one job, never an automatic retry."""

from collections.abc import Mapping
import json
from pathlib import Path
import re
import tempfile

from bloxsmith_app.block_api import BlockRuntimeOutput, BlockRuntimeResult
from .device_process import DeviceError, Cancelled, check_cancel, run_tool, require_success

DEFAULTS = {"printer": "", "copies": 1, "color": "default", "sides": "default", "paper": "default", "orientation": "default", "page_ranges": "", "timeout_sec": 30, "max_file_mb": 50}
FORMATS = {".pdf", ".txt", ".text", ".log", ".csv", ".md", ".ps", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pnm", ".pbm", ".pgm", ".ppm"}


def normalize_config(raw):
    """Validate user choices without inspecting devices during Run preparation."""
    if not isinstance(raw, Mapping):
        raise DeviceError("Printer settings must be an object.")
    config = {**DEFAULTS, **{k: v for k, v in raw.items() if k in DEFAULTS}}
    for key, maximum in (("copies", 100), ("timeout_sec", 120), ("max_file_mb", 200)):
        if type(config[key]) is not int or not 1 <= config[key] <= maximum:
            raise DeviceError(f"{key} must be an integer from 1 to {maximum}.")
    for key, allowed in {"color": ("default", "color", "monochrome"), "sides": ("default", "one-sided", "two-sided-long-edge", "two-sided-short-edge"), "paper": ("default", "A4", "A5", "Letter", "Legal"), "orientation": ("default", "portrait", "landscape")}.items():
        if config[key] not in allowed:
            raise DeviceError(f"Invalid {key} setting.")
    if not isinstance(config["printer"], str) or (config["printer"] and not re.fullmatch(r"[A-Za-z0-9_.-]{1,127}", config["printer"])):
        raise DeviceError("Select a valid installed CUPS printer name.")
    ranges = config["page_ranges"]
    if not isinstance(ranges, str) or len(ranges) > 256 or (ranges and not re.fullmatch(r"[1-9][0-9]*(?:-[1-9][0-9]*)?(?:,[1-9][0-9]*(?:-[1-9][0-9]*)?)*", ranges)):
        raise DeviceError("Page ranges must look like 1-3,5,8-10.")
    if any(len(part.split("-")) == 2 and int(part.split("-")[0]) > int(part.split("-")[1]) for part in ranges.split(",") if part):
        raise DeviceError("A page range cannot end before it starts.")
    return config


def devices():
    """Read configured queues, never discover, install or change system printers."""
    output = require_success(run_tool(["lpstat", "-p"]), "lpstat")
    queues = [{"id": m.group(1), "label": m.group(1)} for line in output.splitlines() if (m := re.match(r"printer (\S+) ", line))]
    code, default, _ = run_tool(["lpstat", "-d"], timeout=5)
    match = re.search(r"system default destination: (\S+)", default) if code == 0 else None
    return {"devices": queues, "default": match.group(1) if match else ""}


def resolve_document(context, directory, limit):
    """Support file ports, explicit JSON path/text, and unambiguous plain text."""
    value = str(context.input_value("document", 1, default=context.input_message) or "")
    kind = context.input_content_type("document", 1, default="text/plain")
    if not value.strip():
        raise DeviceError("The document input is empty.")
    path_value = None
    if kind == "application/json":
        try:
            data = json.loads(value)
        except (ValueError, TypeError) as error:
            raise DeviceError("Expected JSON with exactly one path or text field.") from error
        if not isinstance(data, dict) or set(data) not in ({"path"}, {"text"}) or not isinstance(next(iter(data.values())), str):
            raise DeviceError("Expected JSON with exactly one path or text field.")
        path_value = data.get("path")
        value = data.get("text", "")
    elif kind in {"file/path", "image/path", "application/pdf"}:
        path_value = value
    elif kind != "text/plain" and not kind.startswith("message/"):
        raise DeviceError("Use a file path, plain text, or a JSON path/text object.")
    elif "\n" not in value and (value.startswith(("/", "~/", "./", "../")) or Path(value).suffix.lower() in FORMATS):
        path_value = value
    if path_value is not None:
        if not path_value or "\0" in path_value or len(path_value) > 4096:
            raise DeviceError("Invalid document path.")
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = Path(context.root_dir) / path
        path = path.resolve()
        if not path.is_file():
            raise DeviceError("Document file not found or not a regular file on the BloxSmith host.")
        if path.suffix.lower() not in FORMATS:
            raise DeviceError("Unsupported document format. Convert office documents and web pages to PDF first.")
        size = path.stat().st_size
        if not 0 < size <= limit:
            raise DeviceError("The document is empty or exceeds the configured size limit.")
        # Snapshot a bounded regular file: later upstream edits cannot alter this job.
        snapshot = directory / ("document" + path.suffix.lower())
        with path.open("rb") as source, snapshot.open("xb") as target:
            remaining = limit + 1
            while remaining:
                chunk = source.read(min(65536, remaining))
                if not chunk:
                    break
                target.write(chunk)
                remaining -= len(chunk)
            if target.tell() > limit:
                raise DeviceError("Document grew beyond the configured size limit.")
        return snapshot
    encoded = value.encode("utf-8")
    if not encoded.strip() or len(encoded) > limit:
        raise DeviceError("Text is empty or exceeds the configured size limit.")
    path = directory / "document.txt"
    path.write_bytes(encoded)
    return path


def execute(context):
    """Return the accepted CUPS job ID, not a claim of physical print completion."""
    try:
        config = normalize_config(context.config)
        check_cancel(context)
        queue = config["printer"]
        if not queue:
            output = require_success(run_tool(["lpstat", "-d"], context=context, timeout=5), "lpstat")
            match = re.search(r"system default destination: (\S+)", output)
            if not match:
                raise DeviceError("No default printer is configured. Select an installed printer in the block settings.")
            queue = match.group(1)
            normalize_config({"printer": queue})
        # Inspect the exact queue rather than silently redirecting an unknown name.
        require_success(run_tool(["lpstat", "-p", queue], context=context, timeout=5), "lpstat")
        args = ["lp", "-d", queue, "-n", str(config["copies"]), "-t", "BloxSmith document"]
        for key, option in (("color", "print-color-mode"), ("sides", "sides"), ("paper", "media")):
            if config[key] != "default":
                args += ["-o", f"{option}={config[key]}"]
        if config["orientation"] != "default":
            args += ["-o", "orientation-requested=" + ("3" if config["orientation"] == "portrait" else "4")]
        if config["page_ranges"]:
            args += ["-o", "page-ranges=" + config["page_ranges"]]
        with tempfile.TemporaryDirectory(prefix="bloxsmith-print-") as temporary:
            path = resolve_document(context, Path(temporary), config["max_file_mb"] * 1024 * 1024)
            check_cancel(context)
            response = require_success(run_tool([*args, str(path)], context=context, timeout=config["timeout_sec"]), "lp")
        match = re.search(r"request id is (\S+-\d+)", response)
        if not match:
            raise DeviceError("CUPS returned no job ID. Submission status is unknown: check the print queue before retrying.")
        job = {"job_id": match.group(1), "printer": queue, "status": "submitted", "copies": config["copies"]}
        return BlockRuntimeResult(status="success", outputs=[BlockRuntimeOutput(port_id=1, port_name="job", value=json.dumps(job), content_type="application/json")],
                                  metadata={"print_job": job}, logs=[f"[printer] CUPS accepted job {job['job_id']}; physical completion is not monitored."], last_message=job["job_id"])
    except Cancelled:
        return BlockRuntimeResult(status="cancelled", outputs=[], last_message="Print submission cancelled. Check CUPS: a job already accepted may still print.")
    except (DeviceError, OSError, ValueError) as error:
        message = str(error) if isinstance(error, DeviceError) else "Cannot read the document or access the installed print service."
        return BlockRuntimeResult(status="failed", outputs=[], error=message, last_message=message, logs=[f"[printer-error] {message}"])
