import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { setSeedanceInputVisible, setSeedanceWidgetVisible } from "../web/js/dynamic_widget_ui.js";

let extension, id=0, requests=[];
const frames=new Map();
const toasts=[];
const context=vm.createContext({ app: {registerExtension(value){extension=value;},extensionManager:{toast:{add(value){toasts.push(value);}}}},
    api:{async fetchApi(url,options){requests.push({url,options});return {ok:true,async json(){return {models:["qwen/qwen3.8-flash-next"]};}};}},
    setSeedanceInputVisible,setSeedanceWidgetVisible,resizeSeedanceNode(){},
    requestAnimationFrame(callback){frames.set(++id,callback);return id;},cancelAnimationFrame(key){frames.delete(key);}});
vm.runInContext(fs.readFileSync(new URL("../web/js/llm_ui.js",import.meta.url),"utf8").replace(/^import[\s\S]*?;\r?\n/gm,""),context);
function flush(){for(const [key,callback]of[...frames]){frames.delete(key);callback();}}
class Node {
    constructor(){
        this.widgets=[{name:"model",value:"qwen/qwen3.8-flash-next",type:"combo",options:{},callback(){}},
            {name:"temperature_mode",value:"api_default",type:"combo",callback(){}}, {name:"temperature",value:.6,type:"number"}];
        this.inputs=Array.from({length:4},(_,i)=>({name:`image${i+1}`,link:null}));
        this.inputs.push({name:"api_config",link:7});
        this.graph={links:{7:{origin_id:10}},getNodeById(){return {comfyClass:"Seedance_Config",widgets:[{name:"base_url",value:"https://api.seedance.nz"},{name:"api_key",value:"sk-test"}]};}};
    }
    addWidget(type,name,value,callback){const widget={type,name,value,callback};this.widgets.push(widget);return widget;}
}
await extension.beforeRegisterNodeDef(Node,{name:"Seedance_LLM_API"});
const node=new Node();node.onNodeCreated();flush();
const widget=(name)=>node.widgets.find((w)=>w.name===name);
assert.ok(widget("temperature").type.includes("seedance-hidden"));
widget("temperature_mode").value="custom";widget("temperature_mode").callback();flush();
assert.equal(widget("temperature").type,"number");
widget("model").value="glm-5.3";widget("model").callback();flush();
assert.ok(node.inputs.slice(0,4).every((input)=>input.hidden));
node.inputs[3].link=3;node.onConnectionsChange();flush();assert.ok(!node.inputs[3].hidden);
widget("model").value="qwen/qwen3.8-flash-next";widget("model").callback();flush();
assert.ok(node.inputs.slice(0,4).every((input)=>!input.hidden));
const button=widget("Refresh LLM Models");assert.equal(button.serialize,false);
await button.callback();flush();
assert.equal(requests.length,1);assert.equal(requests[0].url,"/seedance/llm/models");
assert.equal(requests[0].options.method,"POST");
assert.equal(JSON.parse(requests[0].options.body).api_config.base_url,"https://api.seedance.nz");
assert.ok(!requests[0].url.includes("sk-test"));
widget("model").type="converted-widget";widget("model").origType="combo";
await button.callback();flush();assert.equal(widget("model").value,"qwen/qwen3.8-flash-next");
node.graph.getNodeById=()=>({comfyClass:"Unrelated_Config"});
await button.callback();flush();assert.equal(requests.length,2);assert.equal(toasts.length,1);
node.onConfigure();node.onAfterGraphConfigured();flush();
assert.equal(node.inputs.length,5);assert.equal(node.inputs.at(-1).link,7);
console.log("LLM model refresh uses only the local Seedance route, preserves credentials/converted widgets and rejects unrelated config nodes.");
