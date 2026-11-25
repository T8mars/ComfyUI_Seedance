import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode, setSeedanceInputVisible } from "./dynamic_widget_ui.js";

const INSTALLED = Symbol("seedanceMagi2");
const INPUT = /^(image|video|audio)(\d+)$/;

function refresh(node) {
    const value = node.widgets?.find((widget) => widget.name === "generation_type")?.value;
    const linkedMode = node.inputs?.some((slot) => slot.name === "generation_type" && slot.link != null);
    const mode = linkedMode ? "auto" : value;
    const last = { image: 0, video: 0, audio: 0 };
    for (const slot of node.inputs ?? []) {
        const match = INPUT.exec(slot.name);
        if (match && slot.link != null) last[match[1]] = Math.max(last[match[1]], Number(match[2]));
    }
    for (const slot of node.inputs ?? []) {
        const match = INPUT.exec(slot.name);
        if (!match) continue;
        const [, family, rawIndex] = match;
        const index = Number(rawIndex);
        const cap = mode === "text" ? 0 : mode === "frame" ? (family === "image" ? 2 : 0) : Infinity;
        slot.label = mode === "frame" && family === "image" && index <= 2
            ? `${slot.name} (${index === 1 ? "start" : "end"})` : slot.name;
        setSeedanceInputVisible(node, slot, index <= Math.min(cap, last[family] + 1));
    }
    resizeSeedanceNode(node, 480);
}

function schedule(node) {
    if (node.seedanceMagiFrame != null) cancelAnimationFrame(node.seedanceMagiFrame);
    node.seedanceMagiFrame = requestAnimationFrame(() => {
        node.seedanceMagiFrame = null;
        refresh(node);
    });
}

function install(node) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    const widget = node.widgets?.find((item) => item.name === "generation_type");
    if (widget) {
        const callback = widget.callback;
        widget.callback = function (...args) {
            const result = callback?.apply(this, args);
            schedule(node);
            return result;
        };
    }
    schedule(node);
}

app.registerExtension({
    name: "ComfyUI_Seedance.Magi2",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== "Magi_2_Video") return;
        for (const hook of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[hook];
            nodeType.prototype[hook] = function (...args) {
                const result = previous?.apply(this, args);
                schedule(this);
                return result;
            };
        }
    },
    async nodeCreated(node) {
        if (originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass ?? node.type) === "Magi_2_Video") install(node);
    },
});
