import { app } from "../../../scripts/app.js";

const PLUGIN_MODULE = "custom_nodes.ComfyUI_Seedance";
const CONTROL_VALUES = new Set(["fixed", "increment", "decrement", "randomize"]);

function belongsToSeedancePlugin(nodeData) {
    const pythonModule = String(nodeData.python_module ?? "");
    return pythonModule === PLUGIN_MODULE || pythonModule.startsWith(`${PLUGIN_MODULE}.`);
}

function seedControlWidget(node) {
    const seed = node.widgets?.find((widget) => widget.name === "seed");
    if (!seed) {
        return null;
    }
    return seed.linkedWidgets?.find(
        (widget) => widget.name === "control_after_generate",
    ) ?? node.widgets?.find((widget) => widget.name === "control_after_generate");
}

function migrateLegacySeedWidgets(node, info) {
    const widgets = node.widgets ?? [];
    const seedIndex = widgets.findIndex((widget) => widget.name === "seed");
    const control = seedControlWidget(node);
    const controlIndex = widgets.indexOf(control);
    if (seedIndex < 0 || controlIndex < 0 || controlIndex <= seedIndex) {
        return;
    }

    const values = Array.isArray(info?.widgets_values) ? info.widgets_values : [];
    const savedControl = values[controlIndex];
    if (CONTROL_VALUES.has(savedControl)) {
        control.value = savedControl;
        return;
    }

    // Older workflows have no control widget value. ComfyUI has already mapped
    // every later value one position too early, so restore those widgets before
    // dynamic node extensions run their deferred refresh callbacks.
    control.value = "randomize";
    for (let index = controlIndex + 1; index < widgets.length; index += 1) {
        const widget = widgets[index];
        if (widget?.type === "button" || widget?.seedanceApiKeyLink) {
            continue;
        }
        const legacyIndex = index - 1;
        if (legacyIndex < values.length) {
            widget.value = values[legacyIndex];
        }
    }
}

app.registerExtension({
    name: "ComfyUI_Seedance.SeedControlCompatibility",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!belongsToSeedancePlugin(nodeData)) {
            return;
        }
        const requiredSeed = nodeData.input?.required?.seed;
        const optionalSeed = nodeData.input?.optional?.seed;
        const seedOptions = requiredSeed?.[1] ?? optionalSeed?.[1];
        if (!seedOptions?.control_after_generate) {
            return;
        }

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function (info) {
            const result = originalOnConfigure?.apply(this, arguments);
            migrateLegacySeedWidgets(this, info);
            return result;
        };
    },
});
