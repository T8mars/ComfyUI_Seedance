import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { resizeSeedanceNode, setSeedanceInputVisible, setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const KEY = "Seedance_LLM_API";
const INSTALLED = Symbol("seedanceLLMUI");

function refresh(node) {
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    setSeedanceWidgetVisible(widget("temperature"), widget("temperature_mode")?.value === "custom");
    for (const input of node.inputs ?? []) {
        if (/^image[1-4]$/.test(input.name)) setSeedanceInputVisible(node, input, widget("model")?.value !== "glm-5.3");
    }
    resizeSeedanceNode(node, 520);
}

function install(node) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    node.seedanceLLMRefresh = () => {
        if (node.seedanceLLMFrame != null) cancelAnimationFrame(node.seedanceLLMFrame);
        node.seedanceLLMFrame = requestAnimationFrame(() => { node.seedanceLLMFrame = null; refresh(node); });
    };
    for (const name of ["model", "temperature_mode"]) {
        const widget = node.widgets?.find((item) => item.name === name);
        if (!widget) continue;
        const previous = widget.callback;
        widget.callback = function (...args) { const result = previous?.apply(this, args); node.seedanceLLMRefresh(); return result; };
    }
    const button = node.addWidget("button", "Refresh LLM Models", null, async () => {
        if (button.seedanceBusy) return;
        button.seedanceBusy = true;
        button.name = "Refreshing...";
        try {
            const input = node.inputs?.find((item) => item.name === "api_config");
            const body = {};
            if (input?.link != null) {
                const link = node.graph?.links?.[input.link];
                const config = node.graph?.getNodeById(link?.origin_id);
                if (config?.comfyClass !== "Seedance_Config") throw new Error("Connect Seedance API Config directly to refresh models.");
                body.api_config = {
                    base_url: config.widgets?.find((item) => item.name === "base_url")?.value,
                    api_key: config.widgets?.find((item) => item.name === "api_key")?.value,
                };
            }
            const response = await api.fetchApi("/seedance/llm/models", {
                method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
            });
            const result = await response.json();
            if (!response.ok || !Array.isArray(result.models) || result.models.length === 0) throw new Error(result.error || "No LLM models returned");
            const model = node.widgets?.find((item) => item.name === "model");
            if (model && !String(model.type).startsWith("converted-widget") && !Object.hasOwn(model, "origType")) {
                model.options ??= {};
                model.options.values = [...new Set(result.models)];
            }
            button.tooltip = `${result.models.length} chat models from api.seedance.nz`;
        } catch (error) {
            button.tooltip = String(error.message);
            app.extensionManager?.toast?.add?.({ severity: "error", summary: "LLM model refresh", detail: String(error.message), life: 5000 });
        } finally {
            button.seedanceBusy = false;
            button.name = "Refresh LLM Models";
            node.seedanceLLMRefresh();
        }
    });
    button.serialize = false;
    button.tooltip = "Refresh documented chat models from api.seedance.nz using the connected API Config.";
    node.seedanceLLMRefresh();
}

app.registerExtension({
    name: "ComfyUI_Seedance.LLMUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== KEY) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () { const result = created?.apply(this, arguments); install(this); return result; };
        for (const hook of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[hook];
            nodeType.prototype[hook] = function () { const result = previous?.apply(this, arguments); this.seedanceLLMRefresh?.(); return result; };
        }
    },
    async nodeCreated(node) {
        if ((node.comfyClass ?? node.constructor?.comfyClass ?? node.type) === KEY) install(node);
    },
});
