import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode, setSeedanceInputVisible, setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const KEYS = new Set(["Minimax_H3_ComfyUI_CharSwap", "Minimax_H3_ComfyUI_Wuxi", "Minimax_H3_ComfyUI_Max_10020", "Minimax_H3_ComfyUI_Max_10021"]);
const INSTALLED = Symbol("seedanceH3ComfyUI");

function refresh(node, key) {
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    for (const family of ["image", "video", "audio"]) {
        const inputs = (node.inputs ?? []).filter((input) => new RegExp(`^${family}\\d+$`).test(input.name));
        const last = Math.max(0, ...inputs.filter((input) => input.link != null).map((input) => Number(input.name.slice(family.length))));
        for (const input of inputs) setSeedanceInputVisible(node, input, Number(input.name.slice(family.length)) <= last + 1);
    }
    if (key === "Minimax_H3_ComfyUI_CharSwap") {
        const frames = widget("duration_mode")?.value === "frames";
        setSeedanceWidgetVisible(widget("seconds"), !frames);
        setSeedanceWidgetVisible(widget("frames"), frames);
        const resolution = widget("resolution")?.value, ratio = widget("ratio");
        const values = resolution === "auto" ? ["auto"] : ["auto", "16:9", "9:16", ...(resolution === "768p" ? ["1:1", "4:3", "3:4", "21:9"] : [])];
        if (ratio) {
            ratio.options ??= {}; ratio.options.values = values;
            if (!values.includes(ratio.value) && !Object.hasOwn(ratio, "origType") && !node.inputs?.some((input) => input.name === "ratio" && input.link != null)) ratio.value = "auto";
        }
    }
    resizeSeedanceNode(node, 500);
}

function install(node, key) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    node.seedanceH3ComfyRefresh = () => {
        if (node.seedanceH3ComfyFrame != null) cancelAnimationFrame(node.seedanceH3ComfyFrame);
        node.seedanceH3ComfyFrame = requestAnimationFrame(() => { node.seedanceH3ComfyFrame = null; refresh(node, key); });
    };
    for (const field of ["duration_mode", "resolution"]) {
        const widget = node.widgets?.find((item) => item.name === field);
        if (!widget) continue;
        const previous = widget.callback;
        widget.callback = function (...args) { const result = previous?.apply(this, args); node.seedanceH3ComfyRefresh(); return result; };
    }
    node.seedanceH3ComfyRefresh();
}

app.registerExtension({
    name: "ComfyUI_Seedance.H3ComfyUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const key = originalSeedanceNodeName(nodeData.name);
        if (!KEYS.has(key)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () { const result = created?.apply(this, arguments); install(this, key); return result; };
        for (const hook of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[hook];
            nodeType.prototype[hook] = function () { const result = previous?.apply(this, arguments); this.seedanceH3ComfyRefresh?.(); return result; };
        }
    },
    async nodeCreated(node) {
        const key = originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass ?? node.type);
        if (KEYS.has(key)) install(node, key);
    },
});
