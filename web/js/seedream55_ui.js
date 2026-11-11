import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode, setSeedanceInputVisible, setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const KEYS = new Set(["Seedream_5_5_Image", "Seedream_5_5_Layer_Decomposition", "Seedance_2_5_Video", "Seedance_2_5_Draft_To_Video"]);
const INSTALLED = Symbol("seedance55UI");

function refresh(node, key) {
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    const value = (name) => widget(name)?.value;
    if (key === "Seedream_5_5_Image") {
        const edit = String(value("model")).endsWith("-i2i");
        let last = 0;
        for (const input of node.inputs ?? []) {
            if (/^image\d+$/.test(input.name) && input.link != null) last = Math.max(last, Number(input.name.slice(5)));
        }
        for (const input of node.inputs ?? []) {
            if (/^image\d+$/.test(input.name)) setSeedanceInputVisible(node, input, edit && Number(input.name.slice(5)) <= Math.min(10, last + 1));
        }
        const custom = value("resolution") === "custom";
        for (const name of ["width", "height"]) setSeedanceWidgetVisible(widget(name), custom);
        const format = widget("output_format");
        if (format && !String(format.type).startsWith("converted-widget") && !Object.hasOwn(format, "origType")) {
            const allowed = value("background") === "transparent" ? ["png"] : ["png", "jpeg"];
            format.options ??= {};
            format.options.values = allowed;
            if (!allowed.includes(format.value)) { format.value = "png"; format.callback?.("png"); }
        }
    } else if (key === "Seedance_2_5_Video") {
        setSeedanceWidgetVisible(widget("resolution"), !value("draft"));
    }
    resizeSeedanceNode(node, key === "Seedance_2_5_Draft_To_Video" ? 430 : key === "Seedance_2_5_Video" ? 440 : 500);
}

function install(node, key) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    node.seedance55Refresh = () => {
        if (node.seedance55Frame != null) cancelAnimationFrame(node.seedance55Frame);
        node.seedance55Frame = requestAnimationFrame(() => { node.seedance55Frame = null; refresh(node, key); });
    };
    for (const name of ["model", "resolution", "background", "draft"]) {
        const widget = node.widgets?.find((item) => item.name === name);
        if (!widget) continue;
        const previous = widget.callback;
        widget.callback = function (...args) { const result = previous?.apply(this, args); node.seedance55Refresh(); return result; };
    }
    node.seedance55Refresh();
}

app.registerExtension({
    name: "ComfyUI_Seedance.Seedream55DraftUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const key = originalSeedanceNodeName(nodeData.name);
        if (!KEYS.has(key)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () { const result = created?.apply(this, arguments); install(this, key); return result; };
        for (const hook of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[hook];
            nodeType.prototype[hook] = function () { const result = previous?.apply(this, arguments); this.seedance55Refresh?.(); return result; };
        }
    },
    async nodeCreated(node) {
        const key = originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass ?? node.type);
        if (KEYS.has(key)) install(node, key);
    },
});
