import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const NODE_NAME = "MAI_Image_2_6";
const INSTALL_MARKER = Symbol("seedanceMaiImageInstalled");

function refresh(node) {
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    const hasReferences = (node.inputs ?? []).some(
        (input) => /^image[1-5]$/.test(input.name) && input.link != null,
    );
    const automatic = Boolean(widget("auto_aspect_ratio")?.value);
    const size = String(widget("size")?.value ?? "1:1");
    setWidgetVisible(widget("auto_aspect_ratio"), !hasReferences);
    setWidgetVisible(widget("size"), !hasReferences && !automatic);
    setWidgetVisible(widget("resolution"), !hasReferences && (automatic || size !== "custom_pixels"));
    setWidgetVisible(widget("custom_ratio"), !hasReferences && !automatic && size === "custom_ratio");
    setWidgetVisible(widget("width"), !hasReferences && !automatic && size === "custom_pixels");
    setWidgetVisible(widget("height"), !hasReferences && !automatic && size === "custom_pixels");
    resizeSeedanceNode(node, 440);
}

function schedule(node) {
    if (node.seedanceMaiFrame != null) {
        cancelAnimationFrame(node.seedanceMaiFrame);
    }
    node.seedanceMaiFrame = requestAnimationFrame(() => {
        node.seedanceMaiFrame = null;
        refresh(node);
    });
}

function install(node) {
    if (node[INSTALL_MARKER]) return;
    node[INSTALL_MARKER] = true;
    for (const name of ["size", "auto_aspect_ratio"]) {
        const widget = node.widgets?.find((item) => item.name === name);
        if (!widget) continue;
        const callback = widget.callback;
        widget.callback = (...args) => {
            const result = callback?.apply(widget, args);
            schedule(node);
            return result;
        };
    }
    schedule(node);
}

app.registerExtension({
    name: "ComfyUI_Seedance.MaiImageUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== NODE_NAME) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            install(this);
            return result;
        };
        for (const name of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const original = nodeType.prototype[name];
            nodeType.prototype[name] = function () {
                const result = original?.apply(this, arguments);
                schedule(this);
                return result;
            };
        }
    },
    async nodeCreated(node) {
        const name = node.comfyClass ?? node.constructor?.comfyClass
            ?? node.constructor?.nodeData?.name ?? node.type ?? "";
        if (originalSeedanceNodeName(name) === NODE_NAME) install(node);
    },
});
