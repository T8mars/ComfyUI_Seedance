import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode, setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const NODE_NAME = "Zhenzhen_Motion_Video";
const INSTALLED = Symbol("seedanceMotionVideoInstalled");

function refresh(node) {
    const revise = node.widgets?.find((widget) => widget.name === "operation")?.value === "revise";
    for (const name of ["revise_from", "revision_instruction"]) {
        setSeedanceWidgetVisible(node.widgets?.find((widget) => widget.name === name), revise);
    }
    resizeSeedanceNode(node, 460);
}

function schedule(node) {
    if (node.seedanceMotionFrame != null) cancelAnimationFrame(node.seedanceMotionFrame);
    node.seedanceMotionFrame = requestAnimationFrame(() => {
        node.seedanceMotionFrame = null;
        refresh(node);
    });
}

function install(node) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    const operation = node.widgets?.find((widget) => widget.name === "operation");
    if (operation) {
        const callback = operation.callback;
        operation.callback = (...args) => {
            const result = callback?.apply(operation, args);
            schedule(node);
            return result;
        };
    }
    schedule(node);
}

app.registerExtension({
    name: "ComfyUI_Seedance.MotionVideoUI",
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
