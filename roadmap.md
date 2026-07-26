# Midjourney 16 合 1 节点实施路线图

状态：节点、客户端、动态界面、离线测试和 19 份示例工作流已完成。16/16 个 action 均已真实达到动作完成标准；无 mask 的 Modal outpaint 仍是已确认的上游不一致项。

规划日期：2026-07-25

实现日期：2026-07-25

## 0. 实施结果

- 新增注册键 `Midjourney_Multi_Action`，显示名为 `Midjourney 图像与视频（16 合 1）`。
- `MIDJOURNEY_ACTION_SPECS` 显式登记 16 个 action、执行模式、必填字段、条件必填字段、字段白名单和结果类型。
- `web/js/midjourney_action_ui.js` 根据 `operation` 动态显示控件，并保留外部文本和已连接输入。
- 客户端支持异步查询、Describe 同步或异步响应、MODAL 中间状态、图片/视频多产物提取与下载。
- 已生成 16 份一一对应工作流和 3 份常用变体，API Key 为空，任务链通过节点连接传递。
- 全项目 165 项离线测试通过，Python 编译、工作流重生成和 diff 校验通过。
- HTTP Session 已按执行线程隔离；同一线程复用连接，多线程并发不会共享 Session 可变状态。
- 结果提取只遍历任务/结果信封，避免将回显请求或自定义 metadata URL 混入生成结果。
- 已补齐结构化参数版本组合校验、第三查询路由成功形态、`CANCEL` 终态以及图片/视频双占位容错测试。
- Video 与两种 Remix 的 payload 已移除文档未登记的 metadata。
- 16 个 action 均已有真实成功记录；测试使用最多 4 路并发，未发现任务串线，本地 IMAGE/MASK 上传、图片下载、视频下载、文字结果和多结果对齐均成功。
- 无 mask 的 Modal outpaint 请求当前会被上游要求提供 mask；region 模式已完整成功，outpaint 不标记为成功。

真实动作状态：

| action | 状态 | 非敏感结论 |
| --- | --- | --- |
| imagine | 成功 | v6.1 / v8.1 并发完成，四张候选与四宫格已下载 |
| blend | 成功 | 两张参考图完成融合并下载结果 |
| describe | 成功 | 修正真实完成响应的顶层状态解包后复测成功，返回文字结果 |
| edits | 成功 | 图片编辑完成并下载多张结果 |
| upscale | 成功 | index 和 custom ID 两条路径均完成 |
| variation | 成功 | 四宫格选图变体完成 |
| high-variation | 成功 | Upscale 父任务的大幅变体完成 |
| low-variation | 成功 | Upscale 父任务的微调变体完成 |
| reroll | 成功 | 重新生成完成并下载候选图 |
| zoom | 成功 | Upscale 父任务扩图完成 |
| pan | 成功 | Upscale 父任务向右扩图完成 |
| inpaint | 成功 | 两个任务均到达 `MODAL`，节点按合法中间状态返回 |
| modal | 成功 | region 模式完成本地 MASK 上传并下载四张候选与四宫格；无 mask outpaint 当前被上游拒绝 |
| video | 成功 | 直接图片、任务 auto、任务 manual + index、首尾帧四条路径均完成并下载 |
| remix-strong | 成功 | v8.1 父任务强重塑完成 |
| remix-subtle | 成功 | v8.1 父任务弱重塑完成 |

唯一工作目录：`F:\AI-T8-video-onekey\ComfyUI\custom_nodes\ComfyUI_Seedance`

## 1. 目标与边界

- 新增一个 `Midjourney_Multi_Action` 节点，通过 `operation` 覆盖 16 项 Midjourney 操作。
- 采用一个节点、一个显式动作规格表、一个动态前端扩展；不复制 16 套高度相似的节点实现。
- 为每个动作保存一份可导入的必备示例工作流，并为视频和参考图场景补充实用变体。
- 开发完成后，对每个动作进行真实最终状态验证；当前规划阶段不调用生成接口。
- API 配置继续复用 `Seedance API Config`；示例、测试和文档不得保存密钥、真实任务 ID、临时结果地址或运行结果。
- 遵循项目 `skill.md` 的内容边界；`skill.md` 只在真实验证完成后记录非敏感结论，并继续保持 Git 忽略。

## 2. 已核对的官方入口

资料基线：

- `https://api.seedance.nz/docs/llms.txt`
- `https://api.seedance.nz/api/midjourney/actions`
- 当前项目的 `skill.md`、`nodes.py`、`core/client.py`、`core/config.py`、Suno 动态节点与测试

统一约定：

- 提交入口：`POST /v1/midjourney/generations/{action}`。
- `imagine` 也可走不带动作后缀的 `/v1/midjourney/generations`；节点统一使用显式 `/imagine`，便于日志和测试定位。
- 新版路由自动注入 `model=midjourney`，节点不额外显示或发送 `model`。
- 文档同时出现 `GET /v1/tasks/{task_id}`、`GET /v1/midjourney/{task_id}` 和 `GET /v1/midjourney/tasks/{task_id}`。实现前先以只读任务查询确认真实响应，再确定主路径与兼容回退；需要保留 `buttons`、`grid_image_url` 和 `image_urls`。
- 异步状态包括 `NOT_START`、`SUBMITTED`、`IN_PROGRESS`、`MODAL`、`SUCCESS`、`FAILURE`。
- `describe` 是同步动作，但客户端仍须兼容响应只给 `task_id` 的情况，并按响应内容决定是否补充查询。
- `MODAL` 是等待补参的合法状态，不可当作普通失败；只有 `modal` 补参完成后才继续轮询最终结果。

## 3. 十六项动作契约

| operation | 路径后缀 | 执行形态 | 必填或二选一输入 | 前置依赖与关键限制 | 主要结果 |
| --- | --- | --- | --- | --- | --- |
| `midjourney-imagine` | `/imagine` | 异步 | `prompt` | 可选参考图和结构化 MJ 参数 | 四张单图、四宫格、按钮、任务 ID |
| `midjourney-blend` | `/blend` | 异步 | `image_urls` 2–4 张 | `size` 优先于 `dimensions`；不发送 `version` | 图像结果、按钮、任务 ID |
| `midjourney-describe` | `/describe` | 同步优先 | `image_urls` 1 张 | 多传时官方只取第一张；节点应主动限制为一张 | `prompt` / `description` 文本 |
| `midjourney-edits` | `/edits` | 异步 | `prompt` + `image_urls` | 与 imagine 垫图语义不同；允许结构化 MJ 参数 | 1–4 张编辑结果、四宫格、任务 ID |
| `midjourney-upscale` | `/upscale` | 异步 | `task_id` + `index`，或 `task_id` + `custom_id` | 父任务须为成功的四宫格类任务；`index` 为 1–4 | 单图、按钮、新任务 ID |
| `midjourney-variation` | `/variation` | 异步 | `task_id` + `index`，或 `task_id` + `custom_id` | `index` 为 1–4 | 变体图、按钮、新任务 ID |
| `midjourney-high-variation` | `/high-variation` | 异步 | `task_id` + `index`，或 `task_id` + `custom_id` | 通常必须使用 upscale 后的单图任务；无 `custom_id` 时仍需 1–4 的 `index` | 强变体结果、新任务 ID |
| `midjourney-low-variation` | `/low-variation` | 异步 | `task_id` + `index`，或 `task_id` + `custom_id` | 通常必须使用 upscale 后的单图任务；无 `custom_id` 时仍需 1–4 的 `index` | 弱变体结果、新任务 ID |
| `midjourney-reroll` | `/reroll` | 异步 | `task_id`；可选 `custom_id` | 父任务为 imagine/reroll 四宫格，不接受单图衍生任务；不使用 `index` | 新四宫格、四张单图、新任务 ID |
| `midjourney-zoom` | `/zoom` | 异步 | `task_id`；可选 `custom_id` | 父任务须为 upscale 单图；自动匹配时 `zoom_ratio < 2` 选 1.5x，否则选 2x | 扩图结果、新任务 ID |
| `midjourney-pan` | `/pan` | 异步 | `task_id` + `direction`，或 `task_id` + `custom_id` | 父任务须为 upscale 单图；方向为 left/right/up/down；仅文档列出的兼容版本 | 平移扩图、新任务 ID |
| `midjourney-inpaint` | `/inpaint` | 异步到 MODAL | `task_id`；可选 `custom_id` | 父任务须为 upscale 单图；进入 MODAL 后必须在 30 分钟内调用 `modal` | MODAL 任务 ID |
| `midjourney-modal` | `/modal` | MODAL 补参后异步 | inpaint 返回的 `task_id` | `prompt` 可留空继承；有 `mask_url` 为局部重绘，无 `mask_url` 为外扩；局部重绘时透明区域重绘、白色区域保留 | 最终图像，沿用 MODAL 任务链 |
| `midjourney-video` | `/video` | 异步 | 一张首帧 `image_urls`，或 imagine `task_id` | 两种来源互斥；任务模式 `index` 为 0–3；支持可选结束帧 | 1/2/4 个视频结果、任务 ID |
| `midjourney-remix-strong` | `/remix-strong` | 异步 | v8.1/v8.2 父 `task_id` + `index` | `index` 为 1–4；`prompt` 可留空继承 | 强重塑图、新任务 ID |
| `midjourney-remix-subtle` | `/remix-subtle` | 异步 | v8.1/v8.2 父 `task_id` + `index` | `index` 为 1–4；`prompt` 可留空继承 | 弱重塑图、新任务 ID |

### 3.1 Imagine / Edits 结构化参数

两项动作共享以下可选字段，必须通过白名单按需发送：

`size`、`quality`、`style`、`version`、`seed`、`negative_prompt`、`stylize`、`chaos`、`weird`、`tile`、`niji`、`iw`、`cw`、`sw`、`cref`、`sref`、`dref`、`dw`、`repeat`、`raw`、`draft`、`hd`、`stop`、`extra`。

实现要求：

- body 中的结构化字段优先于 prompt 内同名原生参数。
- 数值范围按官方文档做运行时校验，不发送空字符串和占位默认值。
- `extra` 只作为高级逃生口，原样追加到 prompt，不能替代正式字段校验。
- `niji`、`version`、`raw`、`draft`、`hd`、`stop` 的兼容关系写入动作规格和测试，不在前端凭经验推导。

### 3.2 Video 专用参数

- `video_type`：仅允许 `vid_1.1_i2v_480`、`vid_1.1_i2v_720`、`vid_1.1_i2v_start_end_480`、`vid_1.1_i2v_start_end_720`。
- `animate_mode`：`manual` / `auto`；`auto` 必须使用 `task_id + index`。
- `motion`：`low` / `high`。
- `batch_size`：`1` / `2` / `4`。
- `end_url`：可来自本地结束帧或公网 URL；填写后自动选择对应的 start/end 类型。
- 视频动作不接受纯文本输入，也不发送 `speed`。

## 4. 节点与客户端设计

### 4.1 显式动作规格

在 `nodes.py` 中建立 `MIDJOURNEY_ACTION_SPECS`，每项至少固定：

- `endpoint`
- `execution_mode`：`sync` / `async` / `modal_stage`
- `required_all`
- `required_any`
- `mutually_exclusive`
- `allowed_fields`
- `index_range`
- `source_task_kind`
- `result_kind`

所有 payload 都由规格表白名单生成，禁止把节点全部控件无差别发给接口。动作规格同时作为前端显隐、后端校验、测试参数化和工作流审计的唯一事实源。

### 4.2 动态输入

节点显示名建议：`Midjourney 图像与视频（16 合 1）`。

固定入口：

- `operation`
- `prompt`：可转换为外部 STRING 输入；未解析连接时不做空值预判
- `api_config`
- `skip_error`

素材组：

- `image1`–`image4`
- `image_url1`–`image_url4`
- `end_image` / `end_url`
- `mask` / `mask_url`
- `modal_mode`：`region` / `outpaint`，明确控制是否发送遮罩

任务衍生组：

- `task_id`
- `index`
- `custom_id`
- `direction`
- `zoom_ratio`

通用生成组：

- `speed`
- `size`
- `dimensions`
- Imagine / Edits 的结构化参数
- `metadata_json`

视频组：

- `video_type`
- `animate_mode`
- `motion`
- `batch_size`

动态界面要求：

- 新增独立前端扩展，如 `web/midjourney.js`，只显示当前动作相关控件。
- 延续 `web/js/suno_action_ui.js` 已验证的 widget 转输入生命周期；外部 STRING 连线后不丢值、不重复 widget、不因切换动作断线。
- 已转换为输入或仍有连线的控件不能被前端隐藏；无关值可以保留在工作流中，但 payload 白名单不得发送。
- `VALIDATE_INPUTS` 不对尚未解析的外部文本连接做字数或空值判定；所有实际必填和长度校验放到 `execute` 收到真实值之后。
- 本地素材与同槽 URL 互斥；冲突时给出明确的中英双语错误。
- 多余素材不静默发送；例如 describe 只接受第一槽，blend 必须 2–4 槽。
- index 控件根据动作切换范围：普通图像操作 1–4，video 任务复用模式 0–3。
- 可选枚举使用 `unset` / `inherit` 哨兵，避免前端默认值覆盖 prompt 中用户显式写入的参数。

### 4.3 本地素材处理

- 复用项目现有上传与 URL 归一化能力，不新增全局临时状态。
- 本地图片上传后才组装 `image_urls`，保持输入顺序。
- 结束帧单独上传为 `end_url`，不可混入首帧数组。
- `MASK` 转 PNG 时严格映射官方语义：透明区域重绘、白色区域保留；用像素级单元测试锁定极性和 alpha，避免反选。
- `modal_mode=outpaint` 时禁止误发工作流中残留的 `mask` / `mask_url`；`region` 时必须得到有效遮罩。
- 每张本地素材只上传一次；同一次执行中的后续 payload 复用已得到的地址。

### 4.4 响应驱动状态机

客户端建议新增 Midjourney 专用薄封装，继续复用现有 HTTP、超时和下载基础设施：

1. 提交动作并解析同步结果、`task_id` 或 `MODAL`；任务查询路径由开发前的只读响应核对确定，并保留兼容回退。
2. `describe` 若已含文本直接返回；若只含任务标识则查询至可读文本。
3. 普通异步动作按间隔轮询至 `SUCCESS` / `FAILURE`。
4. `inpaint` 以 `MODAL` 作为该动作的预期完成阶段，返回其任务 ID 给下游 `modal`。
5. `modal` 只接受 MODAL 任务，提交后重新进入普通轮询。
6. 对 `429` 做有上限的退避；轮询带 sleep 和轻微抖动，禁止忙循环。
7. 任何失败都带 action、HTTP 状态、服务端原因和脱敏上下文，不暴露认证信息。

### 4.5 输出设计

为保证四宫格、视频批量和后续操作都可直接连接，建议固定输出：

- `image1`–`image4`
- `grid_image`
- `video1`–`video4`
- `text`
- `primary_url`
- `result_urls`
- `primary_path`
- `result_paths`
- `task_id`
- `buttons_json`
- `response`

规则：

- 图像和视频按 API 响应顺序一一下载、解码和输出。
- 缺少的固定槽返回项目约定的空占位，不挤压后续结果序号。
- `grid_image_url` 与四张裁剪图分开保存。
- `buttons_json` 保留 `customId` 与 label，便于高级二次操作和排错。
- `result_urls` 与 `result_paths` 使用 JSON 数组，顺序严格对齐。
- 解析器不得假定所有图片动作固定返回四张；固定输出槽按顺序填充，完整结果始终保留在数组输出中。

## 5. 示例工作流

### 5.1 十六份必备工作流

全部保存到 `examples`，API 配置为空，不包含真实任务数据：

| 文件 | 可运行依赖链 |
| --- | --- |
| `midjourney-imagine文生图.json` | Config → Imagine → 保存四张图 |
| `midjourney-blend多图融合.json` | 两个 Load Image → Blend → 保存结果 |
| `midjourney-describe图生文.json` | Load Image → Describe → 文本输出 |
| `midjourney-edits图片编辑.json` | Load Image + 外部文本 → Edits → 保存结果 |
| `midjourney-upscale放大.json` | Imagine → Upscale(index=1) → 保存单图 |
| `midjourney-variation生成变体.json` | Imagine → Variation(index=1) → 保存结果 |
| `midjourney-high-variation大幅变体.json` | Imagine → Upscale → High Variation → 保存结果 |
| `midjourney-low-variation微调变体.json` | Imagine → Upscale → Low Variation → 保存结果 |
| `midjourney-reroll重新生成.json` | Imagine → Reroll → 保存新四宫格 |
| `midjourney-zoom缩放扩展.json` | Imagine → Upscale → Zoom → 保存结果 |
| `midjourney-pan平移扩展.json` | 兼容版本 Imagine → Upscale → Pan → 保存结果 |
| `midjourney-inpaint局部重绘入口.json` | Imagine → Upscale → Inpaint → 输出 MODAL 任务 ID |
| `midjourney-modal局部重绘完成.json` | Imagine → Upscale → Inpaint + Load Image 的 MASK → Modal(region) → 保存结果 |
| `midjourney-video图生视频.json` | Load Image → Video(batch=1) → 视频输出 |
| `midjourney-remix-strong强重塑.json` | v8.1/v8.2 Imagine → Remix Strong → 保存结果 |
| `midjourney-remix-subtle弱重塑.json` | v8.1/v8.2 Imagine → Remix Subtle → 保存结果 |

### 5.2 三份补充工作流

- `midjourney-imagine参考图.json`：验证本地参考图与 prompt 的组合。
- `midjourney-video任务复用.json`：Imagine → Video，覆盖 0–3 的任务图索引与 auto 模式。
- `midjourney-video首尾帧.json`：首帧 + 结束帧 → Video，覆盖 start/end 类型。
- `midjourney-modal外扩.json` 作为候选补充流程；待开发前确认无遮罩模式的真实响应后决定是否纳入正式示例。

工作流验收：

- 共 19 份 JSON 均能被 ComfyUI 载入。
- 节点类型、widget 顺序、连线索引和输出索引与当前注册表一致。
- 必备链路不依赖手工复制任务 ID。
- 文本输入工作流至少一份使用外部 STRING 节点，防止再次出现连接文本后被默认空值校验拦截。
- 工作流安全扫描不允许出现非空认证字段、真实任务标识、运行结果地址或本地绝对素材路径。

## 6. 测试计划

### 6.1 离线自动化

新增 `tests/test_midjourney.py`，并扩展前端与注册测试：

- 16 项 operation 与 endpoint 精确映射。
- 每项 required/all、required/any、互斥和字段白名单参数化测试。
- Imagine / Edits 结构化参数范围和版本组合。
- Blend 2–4 图、Describe 单图、Video 来源互斥。
- 普通 index 1–4 与 Video index 0–3 分开验证。
- task_id、index、custom_id 的自动匹配与优先级。
- Describe 同步结果、同步仅 task_id、异步成功、失败、超时和 MODAL 状态。
- Inpaint → Modal 的状态传递、30 分钟边界提示和 MASK 极性。
- 图片四槽、四宫格、视频四槽的下载顺序、部分下载失败和解码。
- 外部 STRING 连接场景不触发静态空 prompt 误判。
- 动态前端隐藏/恢复、widget 转输入、刷新和重载。
- 19 份工作流结构、注册名、无敏感数据检查。

### 6.2 后续真实验证矩阵

开发完成后使用临时环境变量注入测试凭据，不写入命令历史、代码、日志或工作流。每项都必须记录提交成功、预期中间状态、最终状态、结果下载和解码：

- 直接素材类：Imagine、Blend、Describe、Edits。
- Describe 必须分别覆盖立即返回非空文本和仅返回任务标识后查询两种响应；`image` 别名只在真实确认支持后开放。
- 四宫格衍生类：Upscale、Variation、Reroll。
- 单图衍生类：High Variation、Low Variation、Zoom、Pan。
- 二阶段类：Inpaint 到 MODAL，再由 Modal 到最终成功；region 和无遮罩 outpaint 分开验证。
- Remix：Strong 与 Subtle 分别使用兼容版本的父任务。
- Video：本地首帧、任务手动复用、任务 auto 复用、首尾帧四个分支分别验证，先使用 `batch_size=1`；其他合法批量值由独立用例覆盖。
- 高级路径：至少选择一个支持按钮的动作真实验证 `custom_id`，同时保留每个动作的自动匹配验证。
- 所有返回的图片、视频和文本必须可读；不能只以“已提交”作为通过。
- 对文档存在矛盾的 Pan、v8 衍生动作和 Video 非法批量值，先做无媒体的校验响应核对，再决定 UI 白名单和正向真实用例。

### 6.3 并发隔离

- 节点和客户端不得使用可变全局 task_id、素材地址、轮询状态或结果缓存。
- 用两个独立队列任务并行执行，确认提交、轮询、下载目录和结果不会串线。
- 用同一前置 Imagine 分叉两个不同衍生动作，确认各自生成独立的新 task_id。
- 模拟一条任务失败、另一条成功，确认错误不会取消或污染另一条。
- 模拟 `429` 后退避重试，确认不会阻塞其他已进入轮询的任务。
- 覆盖同动作四路、混合动作四路以及三条并行 Inpaint → Modal 链，断言任务、遮罩、进度和下载结果不串线。
- 当前客户端 Session 的线程隔离与 UUID 下载文件名必须纳入并发测试，检查连接复用、文件碰撞和覆盖。

## 7. 实施顺序

1. 固化 `MIDJOURNEY_ACTION_SPECS` 与 16 项后端运行时校验。
2. 实现提交、响应归一化、MJ 查询、MODAL 和多媒体下载。
3. 实现 `Midjourney_Multi_Action` 节点及固定输出。
4. 注册节点和显示名，加入 `web/midjourney.js` 动态界面。
5. 完成离线测试和外部文本回归。
6. 生成并审计 19 份示例工作流。
7. 依次执行真实验证矩阵与并发隔离验证。
8. 只把非敏感最终验证结论写入项目 `skill.md`，再更新 README 与本路线图状态。
9. 检查 Git 差异，确保没有凭据、临时文件、任务数据和运行产物后再提交。

## 8. 完成标准

- 一个节点能切换并正确调用全部 16 项动作。
- UI 只展示当前动作需要的字段，外部文本连接正常。
- 每项动作 payload 与官方契约一致，无跨动作字段泄漏。
- 16 项动作全部达到各自真实完成标准；Inpaint 的阶段标准为 MODAL，Modal 的标准为最终成功。
- 三种 Video 输入模式均真实成功。
- 图像、视频、文本、按钮和任务 ID 输出完整且顺序稳定。
- 19 份工作流可直接导入且不含敏感或运行态数据。
- 并发执行无任务串线、无全局锁、无忙轮询。
- 插件全量测试通过，且不破坏现有节点。

## 9. 已识别风险

- 官方公开动作元数据只给出最小必填字段，完整枚举和条件限制仍以 `llms.txt` 各动作章节为准。
- `describe` 在动作元数据中标为同步，但详细文档同时展示 `task_id` 和轮询，必须采用响应驱动而不是硬编码单一路径。
- Describe 的元数据描述提到 `image_urls or image`，详细字段表只登记 `image_urls`；别名不得在未验证前开放。
- 任务查询存在三种文档路径，需确认主路径、状态大小写和 buttons 字段，不能凭路径名称猜测。
- 图像二次操作多为 1–4 索引，Video 任务复用为 0–3，混用会产生隐蔽错误。
- High/Low Variation、Zoom、Pan、Inpaint 依赖 upscale 单图，工作流不能直接接 Imagine 四宫格。
- Pan 专节列出一组兼容版本，其他章节对 HD/v8 后继动作有相反描述；开发前必须用真实父任务确认。
- Remix 只接受 v8.1/v8.2 Imagine 父任务，但 v8 面板对其他后继操作的说明存在冲突，节点需按已验证组合给出清晰错误。
- Inpaint 与 Modal 是时间受限的两阶段流程，不能把 MODAL 当失败，也不能把旧任务静默复用。
- ComfyUI MASK 与接口遮罩语义可能方向相反，必须用像素测试和一次真实局部重绘确认。
- `buttons[].customId` 结构可能随上游变化，自动匹配失败时要保留服务端 buttons 供用户显式选择。
- Video 对非法 `batch_size` 的描述同时存在回退和拒绝两种说法；节点只开放 1/2/4，并用真实校验确认服务端行为。
- Blend、High/Low Variation、Zoom、Pan 的结果数量没有统一承诺，解析器不能硬编码为四张。
- 文档和公开动作元数据都没有 schema 版本；开发时应保存非敏感字段快照，并让测试在动作集合或关键字段变化时显式失败。

---

# Suno 31 合 1 节点实施路线图

状态：已完成。31 项 Suno 操作均已到达真实最终成功状态，对应节点、客户端、动态界面、测试与 31 份示例工作流已齐备。

规划日期：2026-07-25

## 完成结果（2026-07-25）

- 新增一个 `Suno_Music` 节点，通过 `operation` 覆盖官方登记的全部 31 项操作。
- 使用显式 `SUNO_ACTION_SPECS` 固定 action、必填字段、字段白名单、版本集合和结果类型。
- 新增独立音乐提交、任务查询、结果归类、音频解码及视频、图片、通用文件下载。
- 新增动态控件扩展，切换操作时只显示相关字段，并兼容外部文本输入和 ComfyUI widget 转输入生命周期。
- 生成 31 份一一对应的示例工作流；配置字段为空，不保存运行结果。
- 所有结果 URL 与本地路径按响应顺序一一对齐；个别产物下载失败时保留空路径和脱敏警告。
- 本地导入音频执行至少 6 秒的前置校验，三项添加动作示例均先导入音频再串联。
- 音频结果在 `torchaudio` 不可用时自动使用系统、环境变量或整合包内 FFmpeg 解码。
- 全量插件测试共 118 项通过，包含 31 操作请求白名单、失败终态、超时、部分下载、动态界面和工作流安全检查。

### 真实验证矩阵

| operation | 最终状态 | 验证结果 |
| --- | --- | --- |
| `suno-generation` | 成功 | 任务完成；音频、封面均下载，音频解码成功，URL 与路径对齐 |
| `suno-lyrics` | 成功 | 文本结果可读 |
| `suno-upload` | 成功 | 7 秒本地音频上传并建立可复用任务 |
| `suno-extend` | 成功 | 续写结果下载并解码 |
| `suno-cover-song` | 成功 | 补齐真实必需的 `prompt` 后，两条音频下载并解码 |
| `suno-inspo` | 成功 | 本地素材上传、参考生成、两条音频下载并解码 |
| `suno-mashup` | 成功 | 两个真实前置任务串联；补齐 `prompt` 后完成并下载两条音频 |
| `suno-upsample-tags` | 成功 | 返回可读文本；兼容响应驱动的异步查询 |
| `suno-sounds` | 成功 | 音效下载并解码 |
| `suno-create-voice` | 成功 | 返回可读结构化结果 |
| `suno-stems` | 成功 | 4 条音频全部下载并解码 |
| `suno-stems-all` | 成功 | 24 条音频全部下载并解码 |
| `suno-wav` | 成功 | WAV 下载并解码 |
| `suno-generate-mp4` | 成功 | 7 秒导入音频任务生成视频并下载 |
| `suno-concat` | 成功 | 拼接结果下载并解码 |
| `suno-crop` | 成功 | 裁剪结果下载并解码 |
| `suno-fade-in` | 成功 | 淡入结果下载并解码 |
| `suno-fade-out` | 成功 | 淡出结果下载并解码 |
| `suno-remove-section` | 成功 | 删除片段结果下载并解码 |
| `suno-replace-music` | 成功 | 节点级调用完成，4 个结果产物全部下载 |
| `suno-adjust-speed` | 成功 | 变速结果下载并解码 |
| `suno-remaster` | 成功 | 两条音频下载并解码 |
| `suno-midi` | 成功 | 返回可读结构化结果 |
| `suno-bpm` | 成功 | 返回可读分析结果 |
| `suno-aligned-lyrics` | 成功 | 返回结构化对齐时间线，并通过文本输出保留 |
| `suno-persona` | 成功 | 返回可读结构化结果 |
| `suno-vox` | 成功 | 返回可读结构化结果 |
| `suno-sample` | 成功 | 补齐 `prompt` 后，两条音频下载并解码 |
| `suno-add-vocals` | 成功 | 导入音频任务串联；补齐 `prompt` 后，两条音频下载并解码 |
| `suno-add-instrumental` | 成功 | 导入音频任务串联；补齐 `prompt` 后，两条音频下载并解码 |
| `suno-add-stem` | 成功 | 导入音频任务串联；补齐 `prompt` 后，两条音频下载并解码 |

### 已证实的接口差异

- 真实上游要求 `cover-song`、`mashup`、`sample`、`add-vocals`、`add-instrumental`、`add-stem` 在默认模式发送 `prompt`，公开动作注册表暂未完整列出。
- `upsample-tags` 虽在注册表中标记为同步，但真实成功响应可能返回任务标识；客户端按响应决定是否查询。
- `upload` 的本地音频最短为 6 秒；节点在上传前检查。
- `generate-mp4` 对较长生成任务曾连续返回上游 504，改用 7 秒导入音频后真实完成并下载视频；节点不据此编造通用时长上限。
- `replace-music` 曾出现主音频可用而附属视频临时 403，后续重试 4 个产物全部成功；节点仍保留部分产物容错。
- 响应可能同时包含音频、视频、图片和通用文件；节点按原顺序下载，确保 `result_urls` 与 `result_paths` 索引一致。

## 当前实施进度（2026-07-25）

已完成：

- 新增 `Suno_Music` 单节点，`operation` 下拉覆盖官方登记的全部 31 项。
- 使用显式 `SUNO_ACTION_SPECS` 固定每项 action、必填字段、字段白名单、版本集合与结果类型。
- 新增独立音乐提交、任务查询、结果分类和通用文件下载逻辑。
- 音乐任务查询兼容运行阶段的 `data[]` 响应和完成阶段的 `data` 对象响应。
- 音频结果缺少 `torchaudio` 时可自动使用系统或项目内 FFmpeg 解码。
- `suno-upload` 对本地音频执行至少 6 秒的前置校验，避免无效上传。
- 新增前端动态控件扩展，切换 operation 时只显示相关字段，并保留已有连接。
- 已生成 31 份一一对应的示例工作流，配置字段保持空白，不保存运行结果。
- 已新增动作注册表、字段白名单、上传映射、外部文本输入、轮询兼容、解码回退、动态界面和工作流安全测试。

真实验证汇总：

- 全部 31 项均已使用真实前置任务到达最终成功状态；详细结果见文首矩阵。
- 验证记录只保留操作、最终状态与产物检查结论，不写入密钥、任务标识或临时链接。

## 1. 范围与依据

本路线图只针对：

`F:\AI-T8-video-onekey\ComfyUI\custom_nodes\ComfyUI_Seedance`

事实来源：

- 项目唯一工作约束：`skill.md`
- 官方 AI 文档：`https://api.seedance.nz/docs/llms.txt`
- 官方网页文档：`https://api.seedance.nz/docs/`
- 官方动作注册表：`GET https://api.seedance.nz/api/music/actions`
- 当前项目的 `nodes.py`、`core/client.py`、`core/media.py`、测试和示例工作流

2026-07-25 核对结果：

- 用户列出的 31 个 Suno 名称与官方动作注册表中的 31 项完全一致。
- 没有缺项、额外项或重复项。
- Suno 使用独立的 `/v1/music/*` 路径，不能复用 Seed Audio 或 Whisper 的提交接口。
- `suno-generation` 使用 `POST /v1/music/generations`。
- 其余动作使用 `POST /v1/music/generations/{action}`。
- 异步任务使用 `GET /v1/music/tasks/{task_id}` 查询结果。
- `suno-upsample-tags` 在注册表中标记为同步动作，其余 30 项为异步动作。
- 请求体中的 `model` 固定为 `suno`；用户选择的 `suno-*` 名称用于确定 action 路径，不能把 `suno-*` 直接当作请求体 model。

初始规划阶段未发起真实请求；实现完成后按用户要求逐项进行了最小真实验证。

## 2. 设计结论

新增一个节点：

- 注册名：`Suno_Music`
- 显示名：`Suno 音乐生成与处理（31 合 1）`
- Python 类建议：`SunoMusic`
- 分类：`Seedance`

一个节点覆盖全部 31 项，通过 `operation` 下拉框切换。实现必须采用：

1. 显式动作注册表。
2. 每个动作独立的字段白名单。
3. 前端动态显示当前动作所需控件。
4. 后端再次进行动作级严格校验。
5. 同步与异步两条明确执行分支。
6. 固定、稳定的输出合同。

禁止使用“未知 operation 也尝试提交”的通用兜底。任何不在注册表中的值都应立即报错。

## 3. 官方动作矩阵

版本集合缩写：

- `V_ALL`：`v3.5`、`v4`、`v4.5`、`v4.5+`、`v4.5-all`、`v5`、`v5.5`
- `V_INSPO`：`v4`、`v4.5`、`v4.5+`、`v4.5-all`、`v5`、`v5.5`
- `V_REPLACE`：`v4`、`v4.5+`、`v5`、`v5.5`
- `V_REMASTER`：`v4.5+`、`v5`、`v5.5`
- `V_5`：`v5`、`v5.5`
- `V_55`：`v5.5`

| operation | 提交路径 | 模式 | 官方必填字段 | 版本 |
| --- | --- | --- | --- | --- |
| `suno-generation` | `/v1/music/generations` | 异步 | `version`、`prompt` | `V_ALL` |
| `suno-lyrics` | `/v1/music/generations/lyrics` | 异步 | `prompt` | 不发送 |
| `suno-upload` | `/v1/music/generations/upload` | 异步 | `audioFilePath` | 不发送 |
| `suno-extend` | `/v1/music/generations/extend` | 异步 | `task_id`、`continue_at` | `V_ALL`，文档默认 `v5.5` |
| `suno-cover-song` | `/v1/music/generations/cover-song` | 异步 | `task_id`、`prompt` | `V_ALL`，文档默认 `v5.5` |
| `suno-inspo` | `/v1/music/generations/inspo` | 异步 | `audio_urls`，1 至 4 条 | `V_INSPO`，文档默认 `v5.5` |
| `suno-mashup` | `/v1/music/generations/mashup` | 异步 | `task_ids`，恰好 2 个；`prompt` | `V_ALL`，文档默认 `v5.5` |
| `suno-upsample-tags` | `/v1/music/generations/upsample-tags` | 同步 | `tags` | 不发送 |
| `suno-sounds` | `/v1/music/generations/sounds` | 异步 | `prompt` | `V_5`，文档默认 `v5.5` |
| `suno-create-voice` | `/v1/music/generations/create-voice` | 异步 | `audio_url` | 不发送 |
| `suno-stems` | `/v1/music/generations/stems` | 异步 | `task_id` | 不发送 |
| `suno-stems-all` | `/v1/music/generations/stems-all` | 异步 | `task_id` | 不发送 |
| `suno-wav` | `/v1/music/generations/wav` | 异步 | `task_id` | 不发送 |
| `suno-generate-mp4` | `/v1/music/generations/generate-mp4` | 异步 | `task_id` | 不发送 |
| `suno-concat` | `/v1/music/generations/concat` | 异步 | `task_id` | 不发送 |
| `suno-crop` | `/v1/music/generations/crop` | 异步 | `task_id`、`start_s`、`end_s` | 不发送 |
| `suno-fade-in` | `/v1/music/generations/fade-in` | 异步 | `task_id`、`duration_s` | 不发送 |
| `suno-fade-out` | `/v1/music/generations/fade-out` | 异步 | `task_id`、`duration_s` | 不发送 |
| `suno-remove-section` | `/v1/music/generations/remove-section` | 异步 | `task_id`、`start_s`、`end_s` | 不发送 |
| `suno-replace-music` | `/v1/music/generations/replace-music` | 异步 | `task_id`、`start_s`、`end_s` | `V_REPLACE`，文档默认 `v5.5` |
| `suno-adjust-speed` | `/v1/music/generations/adjust-speed` | 异步 | `task_id`、`speed` | 不发送 |
| `suno-remaster` | `/v1/music/generations/remaster` | 异步 | `task_id` | `V_REMASTER`，文档默认 `v5.5` |
| `suno-midi` | `/v1/music/generations/midi` | 异步 | `task_id` | 不发送 |
| `suno-bpm` | `/v1/music/generations/bpm` | 异步 | `task_id` | 不发送 |
| `suno-aligned-lyrics` | `/v1/music/generations/aligned-lyrics` | 异步 | `task_id` | 不发送 |
| `suno-persona` | `/v1/music/generations/persona` | 异步 | `task_id`、`name` | 不发送 |
| `suno-vox` | `/v1/music/generations/vox` | 异步 | `task_id` | 不发送 |
| `suno-sample` | `/v1/music/generations/sample` | 异步 | `task_id`、`start_s`、`end_s`、`prompt` | `V_ALL`，文档默认 `v5.5` |
| `suno-add-vocals` | `/v1/music/generations/add-vocals` | 异步 | `task_id`、`prompt` | `V_5`，文档默认 `v5.5` |
| `suno-add-instrumental` | `/v1/music/generations/add-instrumental` | 异步 | `task_id`、`prompt` | `V_5`，文档默认 `v5.5` |
| `suno-add-stem` | `/v1/music/generations/add-stem` | 异步 | `task_id`、`prompt` | `V_55` |

说明：

- 网页文档把 `suno-generation` 的 `prompt` 标为必填，但动作注册表只列出 `version`。节点按更严格的网页文档处理，运行时同时要求 `prompt` 和 `version`。
- 真实提交确认 `suno-mashup` 在默认模式下还要求 `prompt`；动作注册表目前只列出 `task_ids`。节点按真实接口要求同时校验并发送这两个字段。
- 真实提交确认 `suno-cover-song` 在默认模式下也要求 `prompt`；节点将其与 `task_id` 一起校验并发送。
- 真实提交还确认 `suno-sample`、`suno-add-vocals`、`suno-add-instrumental` 和 `suno-add-stem` 要求 `prompt`；节点均按实际返回补齐显示、校验和发送逻辑。
- `task_audio` 类动作可发送可选的 `audio_index`，从 1 开始，默认 1。
- 没有版本列表的动作不发送 `version`，即使隐藏控件中残留了旧值。
- 文档未给出的选填字段、数值边界和响应字段不自行添加。

## 4. 单节点输入设计

### 4.1 常驻控件

| 控件 | 类型 | 规则 |
| --- | --- | --- |
| `operation` | 31 项下拉框 | 值使用完整 `suno-*` 名称 |
| `api_config` | `SEEDANCE_CONFIG` | 复用现有配置节点 |
| `skip_error` | `BOOLEAN` | 复用项目现有批处理策略 |

### 4.2 生成与文本控件

| 控件 | 类型 | 使用动作 |
| --- | --- | --- |
| `prompt` | 可连接的多行 `STRING` | generation、lyrics、sounds、cover-song、mashup、sample、add-vocals、add-instrumental、add-stem |
| `version` | 官方版本下拉框 | 仅注册表声明版本的动作 |
| `custom` | `BOOLEAN` | generation |
| `instrumental` | `BOOLEAN` | generation |
| `title` | `STRING` | generation |
| `style` | `STRING` | generation |
| `vocal_gender` | `未指定`、`Male`、`Female` | generation |
| `tags` | 多行 `STRING` | upsample-tags |
| `name` | `STRING` | persona |

`prompt`、`tags`、`name`、`task_id` 等字符串必须支持前置文本节点连接。控件预检不能因为本地 widget 暂时为空而错误拦截；真正的必填校验放在运行时进行。

### 4.3 任务引用控件

| 控件 | 类型 | 规则 |
| --- | --- | --- |
| `task_id` | 可连接 `STRING` | 上一个 Suno 节点的 `task_id` 可直接连接 |
| `task_id_2` | 可连接 `STRING` | 仅 mashup 使用 |
| `audio_index` | `INT` | 从 1 开始，默认 1 |

`mashup` 必须得到两个非空且不同输入位置的 task ID，并组装为恰好两项的 `task_ids`。

### 4.4 本地音频与 URL 控件

提供：

- `audio1` 至 `audio4`：可选 `AUDIO`
- `audio_url1` 至 `audio_url4`：可选公网 URL 字符串

规则：

- 同一槽位不能同时连接本地音频和填写 URL。
- 本地音频使用现有 `audio_to_wav_bytes` 转换，再通过 `/v1/files/upload` 取得临时 URL。
- `suno-upload` 只使用第 1 槽，并映射到 `audioFilePath`。
- `suno-create-voice` 只使用第 1 槽，并映射到 `audio_url`。
- `suno-inspo` 按槽位顺序收集 1 至 4 条，映射到 `audio_urls`。
- 其他动作不上传、不发送这些字段。

### 4.5 时间与速度控件

| 控件 | 类型 | 使用动作 |
| --- | --- | --- |
| `continue_at` | `FLOAT` | extend |
| `start_s` | `FLOAT` | crop、remove-section、replace-music、sample |
| `end_s` | `FLOAT` | crop、remove-section、replace-music、sample |
| `duration_s` | `FLOAT` | fade-in、fade-out |
| `speed` | `FLOAT` | adjust-speed |

当前文档没有公布这些字段的完整范围。第一版只校验必填、数字类型和能明确判断的时间顺序，不编造上限；真实测试若返回明确限制，再回填常量、提示和测试。

## 5. 动态界面

新增前端扩展建议：

`web/js/suno_action_ui.js`

行为：

- 根据 `operation` 只显示当前动作相关的控件和未连接输入口。
- 切换动作时保留用户已填值，切回后可继续编辑。
- 隐藏值绝不进入请求；最终以 Python 字段白名单为准。
- 已连接的输入口不强行断开。若它对新动作无效，保持可见并在运行时给出明确提示。
- 节点高度随可见控件稳定调整，避免控件重叠。
- 重新加载旧工作流后再次执行一次可见性刷新。
- 现有 API Key 链接扩展应自动覆盖新节点，不重复添加按钮。

仅靠前端隐藏不构成校验，工作流 JSON 和外部节点仍可能直接传值，后端必须独立保证正确性。

## 6. 请求构造

建议在 `nodes.py` 中建立不可变的 `SUNO_ACTION_SPECS`，每项包含：

- `operation`
- `action`
- `endpoint`
- `sync`
- `reference_type`
- `required_fields`
- `allowed_fields`
- `allowed_versions`
- `default_version`
- `result_family`

请求规则：

1. `suno-generation` 走基础路径，其他动作走显式 action 路径。
2. 请求体 `model` 固定为 `suno`。
3. 仅从当前动作的 `allowed_fields` 取值。
4. 空字符串、未连接输入和本地 UI 哨兵值不发送。
5. 隐藏控件残留值不发送。
6. 不接受未知动作，也不根据字符串自动推测未登记路径。
7. `audio_index` 仅用于任务引用类动作。
8. `mashup` 把两个输入组装为 `task_ids`。
9. URL 类动作先完成本地素材上传，再提交音乐动作。

## 7. 客户端执行层

在 `core/client.py` 中新增独立的音乐客户端函数，不复用 `/v1/audio/generations`：

- `submit_music_action(...)`
- `poll_music_task(...)`
- `extract_music_results(...)`
- `download_music_artifacts(...)`

提交响应需要兼容官方文档中的 `data[0].task_id`。

异步分支：

1. 提交。
2. 获取 task ID。
3. 每 3 至 5 秒查询 `/v1/music/tasks/{task_id}`。
4. 识别 completed、failed 及文档确认的等价终态。
5. 读取 `data.result`，保留完整响应。
6. 下载已识别的短时效结果素材到 ComfyUI 输出目录。

同步分支：

- `suno-upsample-tags` 优先直接解析提交响应。
- 若服务端实际返回 task ID，则进入同一查询逻辑。
- 该分支必须由响应结构决定，不能无条件假定存在 task ID。

沿用当前项目的 Session、Windows 证书处理、超时、重试和进度条，不新增第三方依赖。

## 8. 固定输出合同

建议输出：

| 输出 | 类型 | 说明 |
| --- | --- | --- |
| `audio1` | `AUDIO` | 第一条可解码音频 |
| `audio2` | `AUDIO` | 第二条可解码音频 |
| `video` | `VIDEO` | generate-mp4 的视频结果 |
| `text` | `STRING` | 歌词、标签、分析文本、ID 或摘要 |
| `primary_url` | `STRING` | 第一条主要结果 URL |
| `result_urls` | `STRING` | 全部结果 URL 的 JSON 数组 |
| `primary_path` | `STRING` | 第一条本地转存路径 |
| `result_paths` | `STRING` | 全部本地转存路径的 JSON 数组 |
| `task_id` | `STRING` | 可直接连接到下一实例 |
| `response` | `STRING` | 完整 JSON 响应 |

规则：

- 官方文档常见一次生成返回多条 `music[]`，不能假定永远恰好两条。
- 所有识别出的音频都应转存；前两条提供标准 `AUDIO` 输出，其余路径放入 `result_paths`。
- stems-all 的全部结果必须保留，不能只留下第一条。
- MIDI 等非标准 ComfyUI 类型通过 URL、路径和完整响应输出。
- 没有对应媒体的正常动作，其无关类型输出为 `None`，并在真实 ComfyUI 中验证未连接时不会造成执行异常。
- `skip_error` 继续沿用项目的占位输出思路，同时在 `response` 中返回结构化错误。

动作级响应结构目前没有全部写入官方文档。实现时先保留原始响应；只有文档或真实成功响应确认过的字段才能加入专用提取器。

## 9. 示例工作流

必须保存 31 份工作流，每个 operation 一份：

1. `suno-generation音乐生成.json`
2. `suno-lyrics歌词生成.json`
3. `suno-upload本地音频导入.json`
4. `suno-extend续写.json`
5. `suno-cover-song翻唱换风格.json`
6. `suno-inspo参考音频生成.json`
7. `suno-mashup双曲混合.json`
8. `suno-upsample-tags风格标签扩写.json`
9. `suno-sounds音效生成.json`
10. `suno-create-voice创建音色.json`
11. `suno-stems单分轨.json`
12. `suno-stems-all全分轨.json`
13. `suno-wav导出WAV.json`
14. `suno-generate-mp4生成MV.json`
15. `suno-concat拼接完整歌曲.json`
16. `suno-crop裁剪.json`
17. `suno-fade-in淡入.json`
18. `suno-fade-out淡出.json`
19. `suno-remove-section删除片段.json`
20. `suno-replace-music替换片段.json`
21. `suno-adjust-speed变速.json`
22. `suno-remaster母带处理.json`
23. `suno-midi生成MIDI.json`
24. `suno-bpm分析BPM.json`
25. `suno-aligned-lyrics对齐歌词.json`
26. `suno-persona创建Persona.json`
27. `suno-vox提取人声片段.json`
28. `suno-sample采样生成.json`
29. `suno-add-vocals添加人声.json`
30. `suno-add-instrumental添加伴奏.json`
31. `suno-add-stem添加Stem.json`

工作流结构：

- generation、lyrics、upsample-tags、sounds：单个 Suno 节点。
- upload、create-voice、inspo：`LoadAudio` 连接 Suno 节点，演示本地素材自动上传。
- mashup：两个前置 Suno 任务分别输出 task ID，再连接 mashup 实例。
- 任务引用类：前置 generation 或 upload 实例的 task ID 连接处理实例。
- concat 的正确前置任务类型在真实测试中确认后再固定，不能仅凭名称假设。
- 有标准音频输出的工作流连接 `SaveAudio`。
- generate-mp4 连接 `SaveVideo`。
- 纯文本或结构化结果由 Suno 节点自身展示，不依赖第三方展示节点。

所有示例必须：

- API Key 留空。
- 不保存真实 task ID、结果 URL、本地运行结果或响应内容。
- 使用当前注册名，保证前端测试可以验证。
- JSON 可解析，并通过敏感信息扫描。

## 10. 自动化测试

新增独立文件：

`tests/test_suno_music.py`

至少覆盖：

1. 注册表恰好 31 项，名称与官方列表一致。
2. 每项 endpoint、同步模式、必填字段和版本集合。
3. generation 基础路径与其他 action 路径的差异。
4. 未知 operation 立即失败。
5. 每项只发送白名单字段。
6. 隐藏控件残留值不进入 payload。
7. 外部 STRING 节点连接时，widget 空值不会触发错误预检。
8. 运行时缺少必填字段会给出动作级错误。
9. generation 的 prompt 与 version 双重必填。
10. mashup 恰好两个 task ID。
11. inspo 接受 1 至 4 条引用，并保持槽位顺序。
12. 同一音频槽位的本地素材与 URL 冲突检测。
13. upload、create-voice、inspo 的本地上传字段映射。
14. task_audio 的 `audio_index` 为 1-based。
15. 时间字段按动作发送，其他动作忽略。
16. 同步响应与异步响应分支。
17. 查询中的运行、完成、失败、未知和超时状态。
18. `music[]` 为 1 条、2 条和多条时的提取。
19. 音频、视频、MIDI、文本和元数据结果分类。
20. 所有结果 URL 与本地路径完整保留。
21. `skip_error` 固定输出数量和类型。
22. 31 份工作流都能解析，且每份包含正确 operation。
23. 工作流不包含 API Key、真实 task ID、签名参数或运行结果。
24. 现有全部测试继续通过。

前端测试补充到 `tests/test_frontend_extension.py`：

- 新扩展只作用于 `Suno_Music`。
- operation 切换表覆盖 31 项。
- 必填控件不会被错误隐藏。
- 已连接输入不会被前端断开。
- 节点重载后会刷新可见性。
- API Key 按钮只出现一次。

## 11. 真实测试方案

开发完成后使用用户提供的测试 Key，仅从进程环境或配置节点注入，不写入文件。

最低标准是 31 项逐项真实成功，不按类别抽测：

1. 每个异步动作必须查询到最终成功状态。
2. 仅提交成功或拿到 task ID 不算通过。
3. 有音频结果的动作必须完成下载和 ComfyUI AUDIO 解码。
4. generate-mp4 必须下载并形成可用 VIDEO。
5. MIDI 等文件必须实际下载且非空。
6. lyrics、tags、BPM、aligned-lyrics、persona、voice 等结果必须提取出可读内容，并保留完整响应。
7. stems-all 必须确认全部返回项均被保存。
8. upload、create-voice、inspo 分别测试本地音频自动上传；若文档允许直接 URL，再分别测试 URL 路径。
9. mashup 使用两个真实前置任务。
10. 所有任务引用类动作都使用真实成功任务的 task ID 串联。

建议测试顺序：

1. upsample-tags。
2. generation 两次，建立两个可复用任务。
3. lyrics、sounds。
4. upload 一个短音频。
5. create-voice、inspo、mashup。
6. extend、cover-song、sample、replace-music、remaster。
7. crop、fade-in、fade-out、remove-section、adjust-speed、concat。
8. stems、stems-all、wav、generate-mp4、midi、bpm、aligned-lyrics。
9. persona、vox、add-vocals、add-instrumental、add-stem。

真实测试记录只写入被忽略的 `skill.md`，内容仅保留日期、operation、最终状态、结果类型和下载/解码是否成功，不记录 Key、task ID、结果 URL 或原始响应。

## 12. 预计改动文件

开发阶段预计涉及：

- `nodes.py`
- `core/client.py`
- 必要时小范围调整 `core/media.py`
- `web/js/suno_action_ui.js`
- `tests/test_suno_music.py`
- `tests/test_frontend_extension.py`
- `examples/` 下 31 份 Suno 工作流
- `README.md`
- `pyproject.toml`
- `__init__.py`
- 被忽略的 `skill.md`，仅记录非敏感测试结论

不计划新增 Python 依赖。

## 13. 实施阶段

### 阶段 A：再次冻结接口事实

- 开发开始前重新拉取 llms.txt 和 `/api/music/actions`。
- 确认仍为 31 项且字段未漂移。
- 对文档未写明的字段保持空缺，不自行推断。

### 阶段 B：客户端与动作注册表

- 实现显式 `SUNO_ACTION_SPECS`。
- 实现音乐提交、同步解析、异步查询和结果提取。
- 先完成纯单元测试，不做 UI。

### 阶段 C：31 合 1 节点

- 实现输入、动作级 payload、上传和固定输出。
- 处理外部文本节点连接和 skip_error。
- 注册节点并保持现有节点兼容。

### 阶段 D：动态界面

- 实现 operation 控件联动。
- 在实际 ComfyUI 中检查切换、连接、保存、重载和节点尺寸。

### 阶段 E：31 份示例

- 每项一份最小可理解工作流。
- 优先使用 ComfyUI 核心节点，避免额外插件依赖。
- 逐份解析并扫描敏感信息。

### 阶段 F：逐项真实验证

- 按第 11 节顺序执行。
- 根据真实成功响应补齐专用结果提取器。
- 每补一个响应适配器就增加无敏感值的结构测试。

### 阶段 G：文档与发布检查

- 更新 README、包描述和版本。
- 更新被忽略的 skill.md 测试结论。
- 跑完整测试、编译、JSON 校验和 diff 检查。
- 未经用户明确要求不提交或推送 GitHub。

## 14. 完成标准

只有同时满足以下条件才算完成：

- ComfyUI 中只新增一个 Suno 节点，operation 下拉包含全部 31 项。
- 当前动作只显示相关控件，切换和重载后布局正常。
- 后端使用显式 action 路径和字段白名单。
- 本地音频可自动上传，URL 输入可直接使用。
- 上一个 Suno 节点的 task ID 可直接连接到后续动作。
- 同步与异步动作都能正确完成。
- 31 项每项至少一次真实最终成功。
- 所有可下载结果均已转存并验证对应类型。
- 31 份示例工作流齐全且不包含敏感信息或运行结果。
- 新增测试和现有测试全部通过。
- `skill.md` 继续保持忽略，不进入 GitHub。

## 15. 真实响应后的保留边界

全部 31 项已真实成功，但官方文档仍未逐项完整公布以下通用边界：

- generation 以外动作的全部选填字段不自行增加。
- 时间字段和 `speed` 只校验必填、数字类型与明确的先后关系，不编造上限。
- `audio_index` 从 1 开始；未公布最大值时不增加自定义限制。
- `upsample-tags` 同时兼容直接结果和返回任务标识后查询两种响应。
- 动作专用结果字段继续通过通用递归提取与完整响应输出保留。
- `stems-all` 本次真实返回 24 条音频，但不把观察值写成最大值。
- `concat` 已使用真实续写任务成功串联，但不限制其他官方允许的任务来源。

后续新增或调整 Suno 操作时，继续先核对公开文档和动作注册表，再用最小真实请求确认差异，不依据操作名称推断字段。

## 16. Zhenzhen Nano Banana 与 V3.1 Lite（2026-07-26）

### 范围

- 一个 `Zhenzhen_Image_NB` 节点合并 4 个文档登记模型。
- 4 个模型均支持文生图和最多 14 张参考图编辑。
- 现有 `Zhenzhen_Video_V31` 节点加入 Lite，并按模型限制图片模式。

### 契约

- 图片提交：`POST /v1/image/generations`；查询：`GET /v1/image/generations/{task_id}`。
- 图片请求使用顶层 `model`、`prompt`、`n`、`size`、可选 `images[]`，分辨率写入 `metadata.resolution`。
- NB Flash 固定 1k / n=1；NB 2 支持 0.5k 到 4k / n=1；NB 2 Lite 固定 1k / n=1..4；NB Pro 支持 1k、2k、4k / n=1。
- V3.1 Lite 仅文生视频；V3.1 全系列固定 8 秒，分辨率为 720p、1080p、4k，比例为 16:9、9:16。
- Fast 最多 3 图；Quality 最多 2 图；Lite 禁止图片。

### 工作流

- 4 个 NB 模型各保存文生图和图像编辑工作流，共 8 份。
- 保存 V3.1 Lite 文生视频工作流 1 份。
- 原有 4 份 V3.1 Fast / Quality 工作流迁移到 image3 + api_config 新插槽布局。

### 验证

- 单元测试覆盖模型清单、payload 白名单、模型级参数、14 图上传顺序、V3.1 图片模式和工作流连线。
- 动态界面按 NB 模型切换分辨率、比例和 n，并按 V3.1 模型隐藏不支持的图片插槽。
- 真实 API 验证结果只记录到被忽略的 `skill.md`，不保存 API Key、任务 ID、结果地址或原始响应。
