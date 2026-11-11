import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode, setSeedanceInputVisible } from "./dynamic_widget_ui.js";

const KEYS = new Set(["Minimax_H3_ComfyUI_Max", "Minimax_H3_Image", "Qwen_Image_2_1_Turbo"]);
const INSTALLED = Symbol("h3TurboUI");

function refresh(node, key) {
    for (const prefix of ["image", "audio"]) {
        const inputs = (node.inputs ?? []).filter((input) => new RegExp(`^${prefix}\\d+$`).test(input.name));
        const last = Math.max(0, ...inputs.filter((input) => input.link != null).map((input) => Number(input.name.slice(prefix.length))));
        for (const input of inputs) setSeedanceInputVisible(node, input, Number(input.name.slice(prefix.length)) <= last + 1);
    }
    if (key === "Qwen_Image_2_1_Turbo") {
        const resolution = node.widgets?.find((widget) => widget.name === "resolution");
        if (resolution && !String(resolution.type).startsWith("converted-widget") && !Object.hasOwn(resolution, "origType")) {
            const edit = node.inputs?.some((input) => /^image\d+$/.test(input.name) && input.link != null);
            resolution.options ??= {};
            resolution.options.values = edit ? ["1k", "2k", "720p"] : ["1k", "2k"];
            if (!resolution.options.values.includes(resolution.value)) { resolution.value = "1k"; resolution.callback?.("1k"); }
        }
    }
    resizeSeedanceNode(node, 500);
}

function install(node, key) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    node.h3TurboRefresh = () => {
        if (node.h3TurboFrame != null) cancelAnimationFrame(node.h3TurboFrame);
        node.h3TurboFrame = requestAnimationFrame(() => { node.h3TurboFrame = null; refresh(node, key); });
    };
    node.h3TurboRefresh();
}

app.registerExtension({
    name: "ComfyUI_Seedance.H3TurboUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const key = originalSeedanceNodeName(nodeData.name);
        if (!KEYS.has(key)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () { const result = created?.apply(this, arguments); install(this, key); return result; };
        for (const hook of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[hook];
            nodeType.prototype[hook] = function () { const result = previous?.apply(this, arguments); this.h3TurboRefresh?.(); return result; };
        }
    },
    async nodeCreated(node) {
        const key = originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass ?? node.type);
        if (KEYS.has(key)) install(node, key);
    },
});
