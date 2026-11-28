import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode, setSeedanceInputVisible, setSeedanceWidgetVisible,
} from "./dynamic_widget_ui.js";

const frame = Symbol("seedanceIdeogramFrame");
const hooked = Symbol("seedanceIdeogramControls");

function refresh(node) {
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    const linked = (name) => node.inputs?.some((input) => input.name === name && input.link != null);
    const masked = !linked("mask_url") && Boolean(String(widget("mask_url")?.value ?? "").trim());
    const high = !linked("edit_precision") && widget("edit_precision")?.value === "high";
    const slots = (node.inputs ?? []).filter((slot) => /^image[1-5]$/.test(slot.name));
    const indexOf = (slot) => Number(slot.name.slice(5));
    const last = Math.max(0, ...slots.filter((slot) => slot.link != null).map(indexOf));
    for (const slot of slots) {
        const index = indexOf(slot);
        setSeedanceInputVisible(node, slot,
            slot.link != null || index <= Math.min(last + 1, masked ? 4 : 5));
    }
    setSeedanceWidgetVisible(widget("aspect_ratio"), !masked && !high || linked("aspect_ratio"));
    resizeSeedanceNode(node, 470);
}

function schedule(node) {
    if (node[frame] != null) cancelAnimationFrame(node[frame]);
    node[frame] = requestAnimationFrame(() => {
        node[frame] = null;
        refresh(node);
    });
}

app.registerExtension({
    name: "ComfyUI_Seedance.Ideogram46Edit",
    beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== "Ideogram_V4_6_Edit") return;
        const proto = nodeType.prototype;
        const created = proto.onNodeCreated;
        proto.onNodeCreated = function (...args) {
            const result = created?.apply(this, args);
            if (!this[hooked]) {
                this[hooked] = true;
                for (const field of ["mask_url", "edit_precision"]) {
                    const widget = this.widgets?.find((item) => item.name === field);
                    if (!widget) continue;
                    const previous = widget.callback;
                    const node = this;
                    widget.callback = function (...args) {
                        const result = previous?.apply(this, args);
                        schedule(node);
                        return result;
                    };
                }
            }
            schedule(this);
            return result;
        };
        for (const event of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = proto[event];
            proto[event] = function (...args) {
                const result = previous?.apply(this, args);
                schedule(this);
                return result;
            };
        }
    },
});
