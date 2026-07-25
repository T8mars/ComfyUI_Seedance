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
