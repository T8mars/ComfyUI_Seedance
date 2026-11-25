import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode, setSeedanceInputVisible, setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const KEYS = new Set(["Kling_V4_Long_Image", "HeyGen_Avatar_6", "Miora_3D"]);
const VIEWS = ["front", "left", "right", "back", "top", "bottom", "front-left", "front-right"];
const INSTALLED = Symbol("seedanceNov21");

function refresh(node, key) {
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    const visible = (name, state) => setSeedanceWidgetVisible(widget(name), state);
    const inputs = node.inputs ?? [];
    if (key === "HeyGen_Avatar_6") {
        const fromAudio = inputs.some((slot) => slot.name === "audio" && slot.link != null)
            || Boolean(String(widget("audio_url")?.value ?? "").trim());
        visible("prompt", !fromAudio);
        visible("voice", !fromAudio);
    } else {
        const numbered = inputs.filter((slot) => /^image[1-8]$/.test(slot.name));
        const index = (slot) => Number(slot.name.slice(5));
        const last = Math.max(0, ...numbered.filter((slot) => slot.link != null).map(index));
        const miora = key === "Miora_3D";
        const ecommerce = widget("skill")?.value !== "webpage";
        for (const slot of numbered) {
            if (miora) slot.label = `${slot.name} (${VIEWS[index(slot) - 1]})`;
            setSeedanceInputVisible(node, slot, (miora || ecommerce) && index(slot) <= last + 1);
        }
        if (miora) {
            visible("prompt", last === 0);
            visible("enable_pbr", widget("generate_type")?.value !== "geometry");
        } else {
            visible("length", ecommerce);
            for (const slot of inputs.filter((input) => ["style_image", "subject_image"].includes(input.name))) {
                setSeedanceInputVisible(node, slot, !ecommerce);
            }
        }
    }
    resizeSeedanceNode(node, 510);
}

app.registerExtension({
    name: "ComfyUI_Seedance.Nov21Models",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const key = originalSeedanceNodeName(nodeData.name);
        if (!KEYS.has(key)) return;
        const schedule = (node) => {
            if (node.seedanceNov21Frame != null) cancelAnimationFrame(node.seedanceNov21Frame);
            node.seedanceNov21Frame = requestAnimationFrame(() => {
                node.seedanceNov21Frame = null;
                refresh(node, key);
            });
        };
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function (...args) {
            const result = created?.apply(this, args);
            if (!this[INSTALLED]) {
                this[INSTALLED] = true;
                for (const name of ["skill", "generate_type", "audio_url"]) {
                    const widget = this.widgets?.find((item) => item.name === name);
                    if (!widget) continue;
                    const previous = widget.callback;
                    widget.callback = (...args) => {
                        const value = previous?.apply(widget, args);
                        schedule(this);
                        return value;
                    };
                }
            }
            schedule(this);
            return result;
        };
        for (const hook of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[hook];
            nodeType.prototype[hook] = function (...args) {
                const result = previous?.apply(this, args);
                schedule(this);
                return result;
            };
        }
    },
});
