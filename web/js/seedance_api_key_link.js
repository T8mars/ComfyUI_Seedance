import { app } from "../../../scripts/app.js";

const PLUGIN_MODULE = "custom_nodes.ComfyUI_Seedance";
const API_KEY_BUTTON_LABEL = "获取平价版APIKEY";
const API_KEY_SIGNUP_URL = "https://api.seedance.nz/sign-up?aff=5f4w";
const EXCLUDED_NODE_NAMES = new Set(["Seedance_Config"]);

function belongsToSeedancePlugin(nodeData) {
    const pythonModule = String(nodeData.python_module ?? "");
    return pythonModule === PLUGIN_MODULE || pythonModule.startsWith(`${PLUGIN_MODULE}.`);
}

app.registerExtension({
    name: "ComfyUI_Seedance.APIKeyLink",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (!belongsToSeedancePlugin(nodeData) || EXCLUDED_NODE_NAMES.has(nodeData.name)) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);

            if (!this.widgets?.some((widget) => widget.seedanceApiKeyLink)) {
                const button = this.addWidget("button", API_KEY_BUTTON_LABEL, null, () => {
                    window.open(API_KEY_SIGNUP_URL, "_blank", "noopener,noreferrer");
                });
                button.serialize = false;
                button.seedanceApiKeyLink = true;
            }

            return result;
        };
    },
});
