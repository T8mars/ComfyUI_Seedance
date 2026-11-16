const assert=require("node:assert/strict");
const fs=require("node:fs");
const path=require("node:path");
const {chromium}=require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR,"playwright"));

(async()=>{
    const browser=await chromium.launch({headless:true,executablePath:process.env.SEEDANCE_BROWSER_EXECUTABLE});
    try{
        const page=await browser.newPage({viewport:{width:1700,height:1150}});
        const errors=[];page.on("pageerror",error=>errors.push(error.message));
        await page.goto(process.env.SEEDANCE_LLM_UI_URL,{waitUntil:"networkidle",timeout:90000});
        await page.evaluate(async()=>{window.__llmApp=(await import("/scripts/app.js")).app;});
        await page.waitForFunction(()=>window.__llmApp?.graph);await page.keyboard.press("Escape");
        assert.ok((await(await page.request.post(new URL("/seedance_llm_fixture/reuse",page.url()).href,{data:{}})).json()).ready);
        const directory=path.join(__dirname,"..","examples");
        const tripo=fs.readdirSync(directory).filter(name=>/^tripo-.*-multiview-to-3d示例.json$/.test(name));
        assert.equal(tripo.length,5);
        for(const filename of tripo){
            const report=await page.evaluate(async workflow=>{
                const app=window.__llmApp;await app.loadGraphData(workflow);await new Promise(r=>setTimeout(r,150));
                const node=app.graph._nodes.find(n=>n.comfyClass==="Tripo_Generate");
                const before=node.inputs.map(i=>({name:i.name,link:i.link}));
                const images=node.inputs.filter(i=>/^image[1-4]$/.test(i.name));
                const model=node.widgets.find(w=>w.name==="model");const original=model.value;
                for(const value of ["tripo-h-v3.1-image-to-3d",original]){model.value=value;model.callback?.(value);await new Promise(r=>setTimeout(r,100));}
                node.setSize([900,node.size[1]]);node.setSize([510,node.size[1]]);
                await app.loadGraphData(app.graph.serialize());await new Promise(r=>setTimeout(r,100));
                const restored=app.graph.getNodeById(node.id);const prompt=await app.graphToPrompt();
                const check=await(await fetch("/seedance_llm_fixture/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:prompt.output})})).json();
                return {before,after:restored.inputs.map(i=>({name:i.name,link:i.link})),labels:images.map(i=>i.label),visible:restored.inputs.filter(i=>/^image[1-4]$/.test(i.name)&&!i.hidden).length,check};
            },JSON.parse(fs.readFileSync(path.join(directory,filename),"utf8")));
            assert.deepEqual(report.before,report.after);assert.equal(report.visible,4);
            assert.deepEqual(report.labels,["image1 (front)","image2 (left)","image3 (back)","image4 (right)"]);
            assert.equal(report.check.valid,true,filename+JSON.stringify(report.check));
            console.log("CANVAS PASS "+filename+": four views, labels, resize, mode switch, reload and queue validation");
        }
        async function execute(){return page.evaluate(async()=>{
            const app=window.__llmApp;const graph=await app.graphToPrompt();const {api}=await import("/scripts/api.js");
            const submitted=await fetch("/prompt",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:graph.output,client_id:api.clientId})});
            const body=await submitted.json();if(!submitted.ok)throw new Error(JSON.stringify(body));
            for(let i=0;i<180;i++){const record=(await(await fetch(`/history/${body.prompt_id}`)).json())[body.prompt_id];if(record?.status?.completed){if(record.status.status_str!=="success")throw new Error(JSON.stringify(record.status.messages));return record.outputs;}await new Promise(r=>setTimeout(r,300));}
            throw new Error("Local fixture execution timed out");
        });}
        const files=fs.readdirSync(directory).filter(name=>name.startsWith("SeedanceLLM"));assert.equal(files.length,4);
        for(const filename of files){
            const workflow=JSON.parse(fs.readFileSync(path.join(directory,filename),"utf8"));
            const report=await page.evaluate(async workflow=>{
                const app=window.__llmApp;await app.loadGraphData(workflow);await new Promise(r=>setTimeout(r,100));
                for(const node of app.graph._nodes){if(node.comfyClass==="Seedance_Config")node.widgets.find(w=>w.name==="api_key").value="sk-test";
                    if(node.comfyClass==="Seedance_LLM_API"){node.setSize([900,node.size[1]]);node.setSize([560,node.size[1]]);}}
                await app.loadGraphData(app.graph.serialize());await new Promise(r=>setTimeout(r,100));
                const graph=await app.graphToPrompt();
                return (await fetch("/seedance_llm_fixture/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:graph.output})})).json();
            },workflow);
            assert.equal(report.valid,true,filename+JSON.stringify(report));
            const result=await execute();
            for(const preview of workflow.nodes.filter(n=>n.type==="PreviewAny"))assert.ok(result[String(preview.id)]?.text?.[0]);
            const countURL=new URL("/seedance_llm_fixture/counts",page.url()).href;
            const before=await(await page.request.get(countURL)).json();await execute();
            assert.deepEqual(await(await page.request.get(countURL)).json(),before,"Fixed rerun must not repeat chat POST");
            console.log("NATIVE PASS "+filename+": recorded response, history/preview and Fixed caching");
        }
        const refresh=await page.evaluate(async()=>{
            const app=window.__llmApp;const node=app.graph._nodes.find(n=>n.comfyClass==="Seedance_LLM_API");
            const button=node.widgets.find(w=>w.name==="Refresh LLM Models");await button.callback();
            const model=node.widgets.find(w=>w.name==="model");const values=[...model.options.values];
            const text=LiteGraph.createNode("PrimitiveStringMultiline");app.graph.add(text);text.widgets.find(w=>w.name==="value").value="Reply briefly.";
            window.comfyAPI.widgetInputs.convertToInput(node,node.widgets.find(w=>w.name==="prompt"));text.connect(0,node,node.inputs.findIndex(i=>i.name==="prompt"));
            await app.loadGraphData(app.graph.serialize());await new Promise(r=>setTimeout(r,100));
            const prompt=await app.graphToPrompt();const validation=await(await fetch("/seedance_llm_fixture/validate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({prompt:prompt.output})})).json();
            return {values,validation};
        });
        assert.deepEqual(refresh.values,["qwen/qwen3.8-flash-next","qwen/qwen3.8-max"]);assert.equal(refresh.validation.valid,true);
        await execute();
        await page.request.post(new URL("/seedance_llm_fixture/fail-next",page.url()).href,{data:{}});
        await page.evaluate(()=>{for(const node of window.__llmApp.graph._nodes.filter(n=>n.comfyClass==="Seedance_LLM_API")){node.widgets.find(w=>w.name==="skip_error").value=true;node.widgets.find(w=>w.name==="seed").value+=1;}});
        await execute();
        const output=process.env.SEEDANCE_LLM_SCREENSHOTS;
        if(output){fs.mkdirSync(output,{recursive:true});await page.evaluate(()=>{const app=window.__llmApp;const node=app.graph._nodes.find(n=>n.comfyClass==="Seedance_LLM_API");app.canvas.ds.scale=.8;app.canvas.centerOnNode(node);app.canvas.setDirty(true,true);});await page.waitForTimeout(200);await page.screenshot({path:path.join(output,"llm-desktop.png")});}
        assert.deepEqual(errors,[]);console.log("PASS model refresh excludes media models, connected text, skip_error and zero page errors; all HTTP fixtures local");
    }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
