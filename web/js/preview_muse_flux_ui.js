import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode, setSeedanceInputVisible, setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const NAMES = new Set(["HY_Image_3_5_Preview", "Muse_Image", "Muse_Video", "Flux_3_Image_Variants"]);
const INSTALLED = Symbol("seedancePreviewMuseFluxInstalled");

function refresh(node) {
    const name = node.seedancePreviewName;
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    const flux = name === "Flux_3_Image_Variants";
    const model = String(widget("model")?.value ?? "flux-3-image-t2i");
    const klein = model.includes("-klein-");
    if (flux) {
        setSeedanceWidgetVisible(widget("grounding"), !klein);
        for (const name of ["steps", "output_format"]) setSeedanceWidgetVisible(widget(name), klein);
    }
    if (name === "HY_Image_3_5_Preview") {
        const custom = widget("size")?.value === "custom";
        for (const name of ["width", "height"]) setSeedanceWidgetVisible(widget(name), custom);
        setSeedanceWidgetVisible(widget("resolution"), !custom);
    }
    const maximum = name === "HY_Image_3_5_Preview" ? 5 : flux ? 10 : 9;
    let highest = 0;
    for (const input of node.inputs ?? []) {
        if (/^image\d+$/.test(input.name) && input.link != null) {
            highest = Math.max(highest, Number(input.name.slice(5)));
        }
    }
    const visible = Math.min(maximum, Math.max(1, highest + 1));
    for (const input of node.inputs ?? []) {
        if (/^image\d+$/.test(input.name)) {
            setSeedanceInputVisible(node, input, (!flux || model.endsWith("-i2i"))
                && Number(input.name.slice(5)) <= visible);
        }
    }
    resizeSeedanceNode(node, 460, (node.inputs ?? []).filter((input) => !input.hidden || input.link != null).length);
}

function schedule(node) {
    if (node.seedancePreviewFrame != null) cancelAnimationFrame(node.seedancePreviewFrame);
    node.seedancePreviewFrame = requestAnimationFrame(() => {
        node.seedancePreviewFrame = null;
        refresh(node);
    });
}

function install(node, name) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    node.seedancePreviewName = name;
    for (const name of ["model", "size"]) {
        const widget = node.widgets?.find((item) => item.name === name);
        if (!widget) continue;
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
    name: "ComfyUI_Seedance.PreviewMuseFluxUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const name = originalSeedanceNodeName(nodeData.name);
        if (!NAMES.has(name)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            install(this, name);
            return result;
        };
        for (const hook of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[hook];
            nodeType.prototype[hook] = function () {
                const result = previous?.apply(this, arguments);
                schedule(this);
                return result;
            };
        }
    },
    async nodeCreated(node) {
        const name = originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass
            ?? node.constructor?.nodeData?.name ?? node.type ?? "");
        if (NAMES.has(name)) install(node, name);
    },
});
