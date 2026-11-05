import { app } from "../../../scripts/app.js";
import { resizeSeedanceNode, setSeedanceInputVisible, setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const NAMES = new Set(["Hitem3D_V2", "Hitem3D_Portrait_V2_1", "Meshy_6_Global"]);
const INSTALLED = Symbol("seedanceHitemMeshyInstalled");

function refresh(node) {
    const model = String(node.widgets?.find((widget) => widget.name === "model")?.value ?? "");
    const multi = model.includes("multi-image");
    const meshy = model.startsWith("meshy-");
    const text = model === "meshy-6-global-text-to-3d";
    let visible = text ? 0 : multi ? 2 : 1;
    if (meshy) {
        for (const name of ["prompt", "art_style", "enable_prompt_expansion"]) {
            setSeedanceWidgetVisible(node.widgets?.find((widget) => widget.name === name), text);
        }
        setSeedanceWidgetVisible(node.widgets?.find((widget) => widget.name === "should_texture"), !text);
    }
    if (multi) {
        for (const input of node.inputs ?? []) {
            if (/^image[1-4]$/.test(input.name) && input.link != null) {
                visible = Math.min(4, Math.max(visible, Number(input.name.slice(5)) + 1));
            }
        }
    }
    for (const input of node.inputs ?? []) {
        if (/^image[1-4]$/.test(input.name)) {
            setSeedanceInputVisible(node, input, Number(input.name.slice(5)) <= visible);
        }
    }
    resizeSeedanceNode(node, 430, (node.inputs ?? []).filter((input) => !input.hidden || input.link != null).length);
}

function schedule(node) {
    if (node.seedanceHitemFrame != null) cancelAnimationFrame(node.seedanceHitemFrame);
    node.seedanceHitemFrame = requestAnimationFrame(() => {
        node.seedanceHitemFrame = null;
        refresh(node);
    });
}

function install(node) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    const widget = node.widgets?.find((item) => item.name === "model");
    if (widget) {
        const previous = widget.callback;
        widget.callback = (...args) => {
            const result = previous?.apply(widget, args);
            schedule(node);
            return result;
        };
    }
    schedule(node);
}

app.registerExtension({
    name: "ComfyUI_Seedance.HitemMeshyUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!NAMES.has(nodeData.name)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            install(this);
            return result;
        };
        for (const name of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[name];
            nodeType.prototype[name] = function () {
                const result = previous?.apply(this, arguments);
                schedule(this);
                return result;
            };
        }
    },
    async nodeCreated(node) {
        const name = node.comfyClass ?? node.constructor?.comfyClass ?? node.constructor?.nodeData?.name ?? node.type;
        if (NAMES.has(name)) install(node);
    },
});
