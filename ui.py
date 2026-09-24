"""Release-local, draft/Apply device forms. Reused as a vendored helper per package."""

from html import escape
from bloxsmith_app.block_api import render_inspector_template, render_node_card_template
from .device_process import DeviceError


class DeviceUI:
    """Compose form HTML without owning framework state or global UI registries."""

    def text(self, key, fallback):
        """Return escaped block-owned translatable text."""
        key = f"block.{self.kind}.{key}"
        return f'<span data-i18n="{key}">{escape(self.translate(key, fallback=fallback))}</span>'

    def field(self, config, key, label, *, numeric=False, attrs=""):
        """Keep visible labels associated with their controls on both surfaces."""
        extra = 'type="number" data-block-value-type="integer"' if numeric else 'type="text"'
        return f'<label class="field-group">{self.text(key, label)}<input {extra} {attrs} data-block-config-field="{key}" value="{escape(str(config[key]), quote=True)}"></label>'

    def select(self, config, key, label, choices):
        """Use stable values and catalog-owned display labels."""
        options = ''.join(f'<option value="{escape(value, quote=True)}" data-i18n="block.{self.kind}.option_{value}"{" selected" if str(config[key]) == str(value) else ""}>{escape(self.translate(f"block.{self.kind}.option_{value}", fallback=title))}</option>' for value, title in choices)
        return f'<label class="field-group">{self.text(key, label)}<select data-block-config-field="{key}">{options}</select></label>'

    def settings(self, node):
        """Prioritize device and everyday settings; keep safety limits progressive."""
        config = {**self.defaults, **(node.get("config") or {})}
        scanner = self.kind == "scanner"
        key = "device" if scanner else "printer"
        default = "Select a scanner" if scanner else "System default printer"
        current = str(config[key])
        options = f'<option value="" data-i18n="block.{self.kind}.device_default">{escape(self.translate(f"block.{self.kind}.device_default", fallback=default))}</option>'
        if current:
            options += f'<option value="{escape(current, quote=True)}" selected>{escape(current)}</option>'
        html = ('<section class="device-section">'
                f'<h3>{self.text("equipment", "Equipment")}</h3>'
                f'<label class="field-group">{self.text("name", "Block name")}<input data-block-title-field value="{escape(str(node.get("title") or self.default_title()), quote=True)}"></label>'
                '<div class="device-picker">'
                f'<label class="field-group">{self.text(key, "Scanner" if scanner else "Printer")}<select data-device-select data-block-config-field="{key}">{options}</select></label>'
                f'<button class="ghost-btn" type="button" data-device-refresh>{self.text("refresh", "Refresh")}</button></div>'
                f'<p class="field-hint">{self.text("host_hint", "Uses equipment installed on the BloxSmith host, not on a remote browser’s computer.")}</p>'
                '<p class="device-status" data-device-status role="status" aria-live="polite"></p></section>'
                f'<section class="device-section"><h3>{self.text("settings", "Document settings")}</h3><div class="device-fields">')
        if scanner:
            html += self.select(config, "color", "Color mode", [("color", "Color"), ("gray", "Grayscale"), ("lineart", "Black and white")])
            html += self.field(config, "resolution", "Resolution (dpi)", numeric=True, attrs='min="75" max="600" step="1"')
            html += self.select(config, "source", "Paper source", [("flatbed", "Flatbed · one page"), ("adf", "Feeder · single-sided"), ("adf_duplex", "Feeder · double-sided")])
            html += self.select(config, "paper", "Page size", [("A4", "A4"), ("Letter", "Letter"), ("auto", "Device default")])
            html += '</div></section><section class="device-section">' + f'<h3>{self.text("destination", "PDF destination")}</h3>'
            html += self.field(config, "output_directory", "Output folder", attrs='autocomplete="off" spellcheck="false"')
            html += f'<p class="field-hint">{self.text("directory_hint", "Leave empty to keep PDFs in this block’s persistent storage. A custom folder is created if needed; relative paths use the application folder.")}</p>'
            html += self.field(config, "filename_prefix", "File name prefix", attrs='maxlength="64" spellcheck="false"')
            html += f'<p class="field-hint">{self.text("unique_hint", "A timestamp and unique ID are added. Existing documents are never overwritten.")}</p></section>'
        else:
            html += self.field(config, "copies", "Copies", numeric=True, attrs='min="1" max="100" step="1"')
            html += self.select(config, "color", "Color mode", [("default", "Printer default"), ("color", "Color"), ("monochrome", "Black and white")])
            html += self.select(config, "sides", "Sides", [("default", "Printer default"), ("one-sided", "Single-sided"), ("two-sided-long-edge", "Double-sided · long edge"), ("two-sided-short-edge", "Double-sided · short edge")])
            html += self.select(config, "paper", "Paper size", [("default", "Printer default"), ("A4", "A4"), ("A5", "A5"), ("Letter", "Letter"), ("Legal", "Legal")])
            html += self.select(config, "orientation", "Orientation", [("default", "Printer default"), ("portrait", "Portrait"), ("landscape", "Landscape")])
            html += self.field(config, "page_ranges", "Pages (empty = all)", attrs='placeholder="1-3,5" inputmode="text"')
            html += '</div></section>'
        html += f'<section class="device-section device-help"><h3>{self.text("flow", "How it works")}</h3><p>{self.text("flow_hint", "Run prepares the block. Use Scan on the canvas, or execute this source, to create and send a PDF. Play / One Shot also execute source blocks." if scanner else "Connect a File block, a PDF output, or text to document. Each execution creates a print job. job contains its CUPS ID, not physical completion status.")}</p>'
        html += f'<p class="field-hint">{self.text("run_hint", "Apply settings before Run. If a Run is already loaded, stop it and start it again to use the new settings.")}</p></section>'
        html += f'<details class="device-section"><summary>{self.text("advanced", "Safety limits")}</summary><div class="device-fields device-advanced">'
        html += self.field(config, "timeout_sec", "Timeout (seconds)", numeric=True, attrs='min="5" max="240"' if scanner else 'min="1" max="120"')
        if scanner:
            html += self.field(config, "max_pages", "Maximum feeder pages", numeric=True, attrs='min="1" max="50"')
            html += self.field(config, "max_scan_mb", "Temporary storage limit (MiB)", numeric=True, attrs='min="16" max="512"')
            html += f'<p class="field-hint">{self.text("limits_hint", "Feeder scans stop at this limit or when empty. Unsupported device modes fail explicitly. Stop cancels acquisition without publishing a partial PDF.")}</p>'
        else:
            html += self.field(config, "max_file_mb", "Document limit (MiB)", numeric=True, attrs='min="1" max="200"')
            html += f'<p class="field-hint">{self.text("limits_hint", "PDF, plain text, PostScript and standard images are supported through installed CUPS filters. Convert Office files to PDF. No automatic retry; Stop cannot recall an already accepted print job.")}</p>'
        return html + '</div></details>'

    def render_modal(self, *, node, payload=None):
        """Own an opaque scrollable body and fixed reachable actions."""
        html = (self.directory / "block_modal.html").read_text(encoding="utf-8")
        for key, value in {"node_id": escape(str(node.get("id", "")), quote=True), "node_title": escape(str(node.get("title") or self.default_title())), "settings": self.settings(node)}.items():
            html = html.replace("{{ " + key + " }}", value)
        return {"html": html, "context": {"node_id": node.get("id"), "node_kind": self.kind}}

    def render_inspector_panel(self, *, node, payload=None):
        """Expose exactly the same settings and draft bindings in the inspector."""
        html = (self.directory / "inspector_panel.html").read_text(encoding="utf-8").replace("{{ settings }}", self.settings(node))
        return {"html": render_inspector_template(template=html, node=node, payload=payload), "context": {"node_id": node.get("id"), "full_panel": True}}

    def render_node_card(self, *, node, payload=None):
        """Render only a compact equipment summary and the scanner's explicit action."""
        config = {**self.defaults, **(node.get("config") or {})}
        selected = config.get("device", config.get("printer")) or self.translate(f"block.{self.kind}.device_default", fallback="Select a scanner" if self.kind == "scanner" else "System default printer")
        detail = f'{config["resolution"]} dpi · PDF' if self.kind == "scanner" else f'{config["copies"]} × · {config["paper"]}'
        return render_node_card_template(block=self, node=node, node_classes=[f"{self.kind}-node"], replacements={"title": node.get("title") or self.default_title(), "device": selected, "detail": detail})

    def handle_ui_action(self, *, node, action, values, payload=None):
        """Validate before applying without losing framework-owned execution flags."""
        result = super().handle_ui_action(node=node, action=action, values=values, payload=payload)
        patch = result.get("node_patch") or {}
        if "config" in patch:
            try:
                original = {**(node.get("config") or {}), **patch["config"]}
                patch["config"] = {**original, **self.normalize(original)}
            except DeviceError as error:
                return {"error": str(error)}
        return result

    def handle_ui_request(self, *, node, route, method, values, payload=None):
        """A read-only refresh; printing/scanning never happens in a UI request."""
        if route == "devices" and method.upper() == "POST":
            try:
                return self.discover()
            except (DeviceError, OSError) as error:
                return {"error": str(error), "devices": []}
        return super().handle_ui_request(node=node, route=route, method=method, values=values, payload=payload)
