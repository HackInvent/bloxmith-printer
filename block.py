"""Autonomous printer: CUPS execution and release-owned configuration surfaces."""

from bloxsmith_app.block_api import BlockDefinition, BlockRuntimePreparation
from .runtime import DEFAULTS, normalize_config, execute, devices
from .ui import DeviceUI


# FB1: A file/text input submits one CUPS job and publishes its JSON receipt.
# FB2: Bounded no-shell processes, validated documents, no retry or system changes.
# FB3: The same implementation in centralized and active, managed and linked modes.
# FB4: Accessible, translated and responsive card/modal/inspector surfaces.
class PrinterBlock(DeviceUI, BlockDefinition):
    """Use already installed printers; drivers and queues belong to the OS."""

    kind = "printer"
    defaults = DEFAULTS
    normalize = staticmethod(normalize_config)
    discover = staticmethod(devices)

    def prepare_runtime(self, context):
        """Only validate configuration; never print or probe devices at preparation."""
        normalize_config(context.config)
        return BlockRuntimePreparation()

    def execute_runtime(self, context):
        """Print one received document, with no hidden retry."""
        return execute(context)
