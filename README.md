# ComfyUI_Seedance

## 入口导航

| 入口 | 适合用户 | 说明 | 打开 |
| --- | --- | --- | --- |
| 贞贞的平价AI小铺（国内版） | 国内用户、国内模型优先 | 主要调用国内模型，适合国内模型工作流。 | <a href="https://api.seedance.nz/sign-up?aff=5f4w"><kbd>进入国内版平价AI小铺</kbd></a> |
| 贞贞的AI工坊（海外版） | 海外用户、海外模型优先 | 主要调用海外模型，也包含部分国内模型。 | <a href="https://ai.t8star.org/register?aff=dP7j"><kbd>进入海外版AI工坊</kbd></a> |
| RunningHub APIKEY（国内版） | 需要适配更多 AI 应用的国内用户 | 适配更多 AI 应用，并可体验最新模型。 | <a href="https://www.runninghub.cn/user-center/1819214514410942465/webapp?inviteCode=rh-v1121"><kbd>获取国内版 APIKEY</kbd></a> |
| RunningHub APIKEY（海外版） | 海外模型、更宽松审核场景 | 审核更宽松，支持海外模型。 | <a href="https://www.runninghub.ai/user-center/1907375370302308353/webapp?inviteCode=rh-v1121"><kbd>获取海外版 APIKEY</kbd></a> |

# 👋🏻 Welcome to 贞贞的平价AI小屋

<img src="https://github.com/T8mars/Comfyui-zhenzhen/blob/main/pic/1.png" width="30%" alt="My favorite girl">
My favorite girl Go YounJung

# 网站宗旨：

本站开设初衷是方便粉丝朋友体验最新 AI 模型，仅服务于粉丝朋友，望理解。

Seedance 2.0 / 2.5 / FLUX 3 Video / HappyHorse / Wan 2.7 / Kling / Hailuo 2.3 / Hailuo H3 / MiniMax H3 OW / Vidu Q3 / Zhenzhen Video G 系列视频生成、Zhenzhen Upscaler 视频超分、Seedream / Dola Seedream / Qwen Image 3.0 / Zhenzhen Image G / GK / Nano Banana / Midjourney 图片生成、Seedream 图层拆分、Midjourney 图生视频、Doubao Seed Audio 音频生成、Whisper 语音转写与 Suno 音乐 API 的 ComfyUI 节点插件，默认接入 [api.seedance.nz](https://api.seedance.nz)。

本插件提供视频、图片、音频、语音转写、Suno 音乐与 Midjourney 工作流。Suno 使用一个 31 合 1 节点完成音乐生成、歌词、素材导入、续写、翻唱、参考生成、混合、分轨、导出、编辑和分析；Midjourney 使用一个 16 合 1 节点完成生成、融合、描述、编辑、放大、变体、扩图、局部重绘和图生视频；本地参考素材会自动上传到 API，不需要额外准备图床或外链。

## v0.5.17（2026-08-10）

- 修复 API 后台任务已成功且浏览器可下载，但节点从结果 CDN 立即报 `ConnectionError` 的问题；失效的 `HTTP_PROXY` / `HTTPS_PROXY` 环境变量不再同时拖垮 Python 与系统下载回退。
- 图片、视频、音频和通用结果文件在原连接发生连接/代理错误后，会先用不读取环境代理的独立 Session 直连；仍失败才使用系统 `curl` 和原有重试。
- 下载时限保持 v0.5.16 的快速连接与宽松读取策略：连接 `8s`、读取 `60s`、图片单次总时限 `60s`，视频 `180s`，音频与通用文件 `300s`。
- 不改变节点输入输出、任务提交、轮询、素材上传、HTTP 业务错误处理、媒体完整性校验和并发调度。
- 完整离线回归通过 288 项测试；整合包 Python 成功导入 58 个节点。

## v0.5.16（2026-08-10）

- 所有生成节点的图片、视频、音频和通用结果文件，单次读取等待统一延长到 60 秒，以适应海外结果服务器和较慢的媒体直链。
- 图片单次下载总时限由 45 秒提高到 60 秒；视频仍保留 180 秒总时限，音频和通用文件仍保留 300 秒总时限。
- 连接超时继续保持 8 秒，无法建立连接时仍会快速切换系统下载通道；既有重试、原子落盘、完整性校验和并发失败隔离逻辑保持不变。
- 完整离线回归通过 287 项测试，135 份示例工作流通过 JSON 与敏感信息审计。

## v0.5.15（2026-08-10）

- 将 `v0.5.14` 的图片下载恢复机制扩展到全部视频、Seed Audio、Suno 音视频和通用结果文件，以及 Midjourney 视频结果。
- 视频、音频和通用文件首次发生连接、TLS、读取或完整性错误时，会立即关闭当前线程连接并切换系统 `curl`，不额外等待；系统通道失败后再以 1 秒、2 秒短间隔使用全新 Python Session。
- 所有文件型结果先写入 `.part`，确认非空且与响应长度一致后再原子替换最终文件；失败、中断和重试都会清理临时文件。
- 视频下载完成后必须通过 MP4 `ftyp` 头校验，音频必须成功解码为 ComfyUI `AUDIO`；返回网页、截断内容或损坏媒体不会被误当成成功结果。
- 真实强制故障验证：4 秒 480p 视频通过系统通道约 0.2 秒下载为有效 MP4；Seed Audio WAV 约 2.4 秒下载并解码为 24 kHz 双声道波形。完整离线回归通过 286 项测试，135 份示例工作流通过 JSON 审计。

## v0.5.14（2026-08-10）

- 修复图片任务已经成功、但 Python 下载结果直链发生 `ConnectionError` 时 ComfyUI 无法预览或保存图片的问题。
- 所有图片生成节点统一使用浏览器兼容请求头；首次连接、TLS 或读取错误会立即关闭当前线程连接并切换系统 `curl` 下载，不额外等待。
- 系统下载通道不可用或失败时，会通过全新 Python Session 在 1 秒、2 秒后继续重试；签名结果 URL 不进入进程参数、控制台日志或最终错误信息。
- 节点输入、输出和工作流结构保持不变；普通图片、图层拆分、Midjourney 图片及 30 路图片并发均复用同一恢复链路。
- 使用真实 NB Flash 1K 任务强制模拟 Python `ConnectionError`，系统通道在约 6.1 秒内下载并解码为 `1×1024×1024×3` ComfyUI 张量；完整离线回归通过 280 项测试，135 份示例工作流通过 JSON 审计。

## v0.5.13（2026-08-09）

- 全部 29 个生成与处理节点统一提供 ComfyUI 标准 `seed` 控件，支持 `fixed`、`randomize`、`increment` 和 `decrement`。
- `fixed` 状态下，节点所有输入保持不变时会复用 ComfyUI 缓存，不会重复提交任务；修改种子或任一其他输入后会重新执行。
- 原生支持种子的模型继续按原有位置、默认值和请求格式透传；其余节点的种子只参与本地缓存判断，不会改变既有 API 请求。
- 并发提交节点同步支持种子缓存，并发接收节点继续实时等待各路结果；固定种子不会影响单路失败隔离。
- 新增旧工作流控件迁移：没有保存种子控制状态的工作流默认使用 `randomize`，已有字段和连线顺序保持不变。
- 完整离线回归通过 275 项测试，135 份示例工作流通过 JSON 与敏感信息审计。

## v0.5.12（2026-08-09）

- 新增 `MiniMax H3 OW Fast 视频生成（2 合 1）` 节点，包含 `minimax-h3-ow-i2v-fast` 与 `minimax-h3-ow-r2v-fast`。
- I2V Fast 严格使用 1 张首帧图；R2V Fast 支持 1 到 9 张参考图。两者支持 5/10/15 秒、480p/720p 与 8 种画幅，并提供独立视频并发提交节点。
- Hailuo H3 国内模型默认分辨率及三份示例工作流更新为 `768P`，同时继续保留 `2K` 选项和既有工作流兼容性。
- 两个 Fast 模型均完成最小规格真实生成、轮询、下载与 MP4 校验。Hailuo H3 Multi 也已完成 5 秒 `768P` 真实生成与 MP4 校验；T2V 与 I2V 已真实提交，但当前测试凭证在任务创建前被接口拒绝，未记录为生成通过。
- 完整离线回归通过 268 项测试，135 份示例工作流通过 JSON 与敏感信息审计。

## v0.5.11（2026-08-09）

- 新增独立的 `Seedream v5 Pro 图层拆分` 节点，接入 `seedream-v5-pro-layer-decomposition`；单图输入，提示词可选，支持 `auto` / `1k` / `1.5k` / `2k` 与 PNG/JPEG。
- 节点完整遍历 `image_urls`，按 API 顺序输出 IMAGE 与 MASK 列表：第 1 项为底图，后续为全部图层；不同尺寸结果不会被缩放、拼批或截断。
- 透明通道转换为标准 ComfyUI MASK。新增示例工作流使用原生 `Join Image with Alpha` 逐项恢复 RGBA，并由 `Save Image` 保存全部结果，无需额外辅助节点。
- 最低规格真实节点验证返回 6 张图片，6 个 URL、6 个 IMAGE、6 个 MASK 与 `image_count` 完全一致；底图和 5 个异尺寸透明图层均成功下载与解码。
- 完整离线回归通过 264 项测试，133 份示例工作流通过 JSON 与敏感信息审计。

## v0.5.10（2026-08-09）

- 全部 27 个 API 生成节点统一支持默认关闭的 `skip_error`；开启后，单个任务失败会返回符合原输出类型的占位结果并继续执行下游工作流。
- 补齐 Seedream、Zhenzhen Image G、Qwen Image 3.0、Zhenzhen Image GK v1.5 和 Nano Banana 图像节点的错误占位输出，URL 与任务字段在失败时保持为空。
- 并发提交任务会逐路保留 `skip_error` 策略；即使并发接收节点保持默认 `failure_mode=raise`，开启跳错的单路失败也不会取消其他图片或视频任务。
- 严格预检失败会直接转为可跳过的失败 Future，不会继续请求 API；未开启 `skip_error` 时仍保持原有失败即报错行为，兼容既有工作流。
- 完整离线回归通过 255 项测试并审计 132 份示例工作流；内置 ComfyUI Python 环境通过全部 22 项跳错与并发专项测试。

## v0.5.9（2026-08-08）

- Hailuo H3 节点新增海外 T2V、I2V、Multi 三个模型，现有节点扩展为国内/海外 6 合 1，并按最新文档支持 `768P` 与 `2K`。
- 新增 `FLUX 3 视频生成与草稿增强（8 合 1）` 节点，覆盖国内/海外 T2V、I2V、V2V 与 Draft Enhance；I2V 支持最多 10 张关键帧，V2V 可连接本地视频或填写公网 MP4 直链。
- FLUX 3 支持 5 到 20 秒、HD/FHD、文档列出的 8 种比例、草稿缓存、音频开关和安全容忍度；前端按模型动态显示适用素材与参数。
- H3 新增 3 份海外模型工作流，FLUX 3 新增 8 份逐模型工作流；Draft Enhance 示例通过节点连线传递 `draft_cache`，认证字段和运行结果保持空白。
- 已对 3 个 H3 Global 模型和 8 个 FLUX 3 模型逐一完成最小时长真实生成，11 条路径均返回有效 MP4；H3 Global Multi 同时使用图片、视频和音频，两条 Draft Enhance 均使用同线路真实草稿缓存完成。
- 完整离线回归通过 250 项测试并审计 132 份示例工作流；ComfyUI 实机画布已验证 FLUX 3 模式切换、媒体插槽恢复和 H3 Global 多模态连线。

## v0.5.8（2026-08-07）

- 按最新 API 文档将 Seedance 2.5 Multi 扩展到最多 30 张图片、10 个视频和 10 段音频，总计 50 个参考素材。
- Seedance 2.5 使用独立素材上限，原 Seedance 2.0、Hailuo 等节点的既有素材数量与行为保持不变。
- Multi 前端按图片、视频、音频各显示一个可连接的下一插槽，连接后逐步展开，避免 50 个输入一次铺满节点。
- 六份 Seedance 2.5 示例工作流已迁移到新的 50 素材输入契约，并保持 API Key 与运行结果为空。
- 已用国内 Multi 完成 10 张参考图、4 秒、480p 的真实生成，并校验结果为有效 MP4 流，确认不再受旧版 9 图上限影响。

## v0.5.7（2026-08-07）

- 新增 `Seedance 2.5 Standard 视频生成（6 合 1）` 节点，合并国内与海外的 T2V、I2V 和 Multi 六个模型。
- 支持 4 到 30 秒以及模型智能时长，分辨率覆盖 `480p`、`720p`、`1080p`、`2k`、`4k`。
- I2V 支持必填首帧与可选尾帧；Multi 按 `metadata.content` 混合提交图片、视频和音频。
- 前端按模型动态显示素材输入，原节点与配套并发提交节点均可连接现有 10 路视频并发接收节点。
- 新增六份逐模型示例工作流；两份 Multi 示例均预接图片、视频和音频，API Key 保持空白。
- 视频结果改为带连接/读取时限的流式下载，使用 `.part` 临时文件完整写入后再原子落盘；慢连接会自动清理并重试，不再留下 0 字节最终文件。
- 六个模型均已使用 4 秒、480p 完成真实生成与结果下载；两个 Multi 路径同时传入图片、视频和音频，国内/海外 I2V 均由 `ffprobe` 验证为 H.264、854×480、97 帧、约 4.04 秒。
- 完整离线回归共 236 项测试通过，121 份示例工作流 JSON 全部通过解析与安全检查。

## v0.5.6（2026-08-06）

- 新增 `Qwen Image 3.0 / Pro 图像生成/编辑（8 合 1）` 节点，覆盖国内与海外的标准版、Pro 版 T2I/I2I 模型；I2I 支持 1 到 3 张参考图。
- Qwen 尺寸严格分为自动、`metadata.ratio + metadata.resolution` 和顶层自定义 `size` 三种模式，支持 `n=1..6`、负面提示词、提示词扩写和可选 seed。
- 新增 `MiniMax H3 OW 视频生成（3 合 1）` 节点，覆盖 T2V、I2V、R2V；支持 5/10/15 秒、480p/720p 与文档规定的 8 种画幅。
- 两个节点均提供配套并发提交版本，可分别连接现有 30 路图片或 10 路视频并发接收节点；前端会按模型和尺寸模式动态显示适用控件。
- 动态素材插槽兼容当前 ComfyUI 画布实现：不适用且未连接的插槽移出绘制区域，已有连线和工作流插槽索引保持不变。
- 新增 11 份逐模型示例工作流，文生路径无需素材，图像编辑、图生视频和参考生视频工作流均预接本地参考图。
- 已完成 8 个 Qwen 模型与 3 个 MiniMax 模型的真实生成、轮询、下载和解码验证；3 个视频均为 480p、约 5 秒的有效 MP4。
- 完整离线回归共 222 项测试通过，覆盖参数分流、素材限制、并发注册、动态前端和工作流安全。

## v0.5.5（2026-08-04）

- 新增可选并发工作流，图片与视频分别使用独立线程池，单个接收节点固定支持 30 路图片或 10 路视频。
- 为 4 个图片节点、15 个视频节点增加并发提交版本；Midjourney 图片与视频使用各自的专用提交节点，避免混合输出误分类。
- 并发接收节点保持槽位顺序，默认在任一任务失败时明确报错，也可选择仅替换失败槽并输出脱敏状态摘要。
- 原有节点、参数和工作流保持不变；新增 2 路最小验证与 30/10 路完整示例共 4 份。
- 已完成 30 张图片与 10 段 4 秒视频的同批真实验证，全部生成、下载并转换为有效 ComfyUI 媒体输出。
- 配置节点会在请求前检查 API Key，避免把提示词误填到 `api_key` 时出现难以理解的请求头编码错误。
- 修复所有动态参数节点在缩放后隐藏控件仍被绘制、与可见控件重叠的问题，覆盖 Zhenzhen Image G/NB/V3.1、Hailuo H3、Suno、Midjourney 及其并发提交版本。
- 动态控件改为统一使用 ComfyUI 兼容的隐藏与恢复机制，并完成真实画布模型切换、节点缩放和前端日志检查。
- Lowprice 提示词按上游真实限制在提交前校验 5 到 5000 字符；并发提交节点会在创建 Future 前单独报告提示词错误，不会把一条错误展开成全部输入无效，也不会延迟到接收阶段。
- 已按用户同结构工作流真实复测两路 Lowprice 图像编辑：共用一张参考图并发提交，两路均成功完成并由同一接收节点输出有效图片。
- 并发接收节点会汇总每个子任务的上传、轮询与下载进度，不再只在整个 Future 完成后跳动。
- 图片结果改为流式读取；单次连接使用较短的连接/读取超时和 45 秒总时限，遇到损坏分块或慢连接会尽快关闭并重试，避免 API 已完成后长时间停在接收节点。

## v0.5.4（2026-07-31）

- 新增 `Hailuo H3 视频生成` 三模型合一节点，支持 `hailuo-h3-t2v`、`hailuo-h3-i2v` 与 `hailuo-h3-multi`。
- H3 固定 2K，支持 5 到 15 秒；I2V 支持首尾帧，Multi 支持最多 9 图、3 视频和 3 音频。
- 前端会按模型动态显示可用素材输入，并新增文生视频、首尾帧图生视频和多模态参考生视频三份工作流。
- 三个模型均已完成 5 秒真实生成和结果下载；Multi 同时验证了图片、视频、音频输入。

## v0.5.3（2026-07-27）

- 优化 `Zhenzhen Image G 图像生成/编辑` 的 Lowprice `size` 控件，改为常用比例下拉。
- 新增 `custom` 模式，支持手动填写比例或 `WxH`，并仅在选择 `custom` 时显示输入框。
- 兼容旧工作流中的自由尺寸，同时更新 Lowprice 与 G-2 的四份示例工作流。

## v0.5.2（2026-07-27）

- 优化 `Midjourney 图像与视频（16 合 1）` 节点，下拉项在 action ID 后显示中文用途。
- `size` 改为常用比例选择，并提供 `custom` 手填 `w:h` 比例；仅选择 custom 时显示手填框。
- 默认使用 `relax`、`1:1`、`quality=1`、`version=8.2`、`SQUARE` 和向右平移，旧工作流中的 `unset`、空比例及自由比例会自动迁移。
- 同步更新 19 份 Midjourney 示例工作流。

## v0.5.1（2026-07-26）

- 修正同一节点内 G-2 与 `zhenzhen-image-g-v2-lowprice` 的参数分流，Lowprice 现为默认模型。
- Lowprice 支持 `1k` / `2k` / `4k`、顶层 `size`、`n=1..10` 和最多 16 张可选参考图。
- G-2 两个模型继续使用固定 `1k` 与 `metadata.ratio`，图像编辑最多 10 张参考图。

## v0.5.0（2026-07-26）

- 新增 `Zhenzhen Image Nano Banana 生成/编辑` 节点，一个节点合并 `zhenzhen-image-nb-flash`、`zhenzhen-image-nb-2`、`zhenzhen-image-nb-2-lite` 和 `zhenzhen-image-nb-pro`。
- 四个模型均支持文生图和最多 14 张参考图编辑；节点按模型动态限制 `resolution`、`size` 和 `n`。
- `Zhenzhen Video V3.1` 节点新增 `zhenzhen-video-v31-lite`，Lite 仅支持文生视频；V3.1 时长固定为 8 秒，并支持 720p、1080p 和 4k。
- V3.1 Fast 支持最多 3 张参考图，Quality 禁止三图 reference，Lite 禁止任何图片输入；前端会自动隐藏当前模型不支持的图片插槽。
- 新增 8 份 Nano Banana 文生图/图像编辑工作流和 1 份 V3.1 Lite 文生视频工作流；原有 4 份 V3.1 工作流已迁移到新插槽布局。

## v0.4.0（2026-07-25）

- 新增 `Midjourney 图像与视频（16 合 1）` 节点，覆盖官方登记的 16 个操作。
- 使用独立 `/v1/midjourney/*` 客户端、显式动作规格表和动作级字段白名单；任务查询兼容三条官方文档路径。
- 动态界面仅显示当前操作需要的字段，并保留外部 STRING 连线和已连接输入。
- 支持最多 4 张本地图片或公网 URL、结构化生成参数、任务 ID / custom ID 串联、ComfyUI MASK、首尾帧视频和 1 / 2 / 4 路视频结果。
- 固定输出 4 张候选图、四宫格、4 路视频、文本、全部结果 URL / 本地路径、任务 ID、按钮 JSON 和完整响应。
- 新增 19 份示例工作流，覆盖全部 16 个操作，并补充参考图、任务复用视频和首尾帧视频。
- 全量插件测试 165 项通过；16 个操作均已达到各自文档终态，图片、视频、文字、任务串联、本地素材上传和最多 4 路并发均正常。
- Describe 的真实完成响应兼容已修正并复测成功；Modal 的 region 模式已完成 MASK 上传和最终图片下载。文档所述无 mask outpaint 当前仍被上游要求提供 mask，保留为上游待修复项。

## v0.3.0（2026-07-25）

- 新增 `Suno 音乐生成与处理（31 合 1）` 节点，一个 `operation` 下拉覆盖官方登记的全部 31 项。
- 使用独立 `/v1/music/*` 客户端、显式 action 注册表和动作级字段白名单，支持同步响应与异步任务查询。
- 动态界面只显示当前操作所需字段；`prompt`、任务 ID 和 URL 均可连接前置字符串节点。
- 支持本地音频自动上传、公网音频 URL、最多 4 段参考音频，以及前后 Suno 节点的任务串联。
- 固定输出最多两路 `AUDIO`、一路 `VIDEO`、文本、全部结果 URL/本地路径、任务 ID 和完整响应。
- 新增 31 份一一对应的示例工作流，并补充完整动作、前端联动、结果提取和工作流安全测试。
- 已逐项真实验证全部 31 个操作到达最终成功状态；可下载产物均完成转存，音频完成解码，MV 使用 7 秒导入音频任务验证。
- 全量插件测试 118 项通过，覆盖字段白名单、外部文本输入、失败与超时、部分产物容错、动态控件和示例安全检查。

## v0.2.10（2026-07-25）

- 新增 `Zhenzhen Image GK v1.5 图像生成/编辑` 节点，合并 `zhenzhen-image-gk-v15` 与 `zhenzhen-image-gk-v15-edit`。
- 节点支持顶层 `size` 与 `n` 参数；编辑模型需要连接 `image1`，并按文档只提交第一张参考图。
- 新增 GK v1.5 文生图和图像编辑示例工作流。
- 已按最新 API 文档完成节点、示例和本地校验；真实提交检查遇到上游 429，按确认不继续重试。

## v0.2.9（2026-07-25）

- 新增 `Whisper 1 语音转写` 节点，接入同步 `/v1/audio/transcriptions` multipart 接口。
- 节点输入 ComfyUI `AUDIO`，自动转换为 wav 上传，输出转写文本和原始响应。
- 支持 `json`、`verbose_json`、`srt`、`text`、`vtt` 五种 `response_format`。
- 已真实验证 `whisper-1` 可完成最小音频转写请求并返回文本。

## v0.2.8（2026-07-25）

- Zhenzhen Image G 节点新增 `zhenzhen-image-g-v2-lowprice`，与 G-2 模型共用节点；该模型可纯文生图，也可连接参考图后通过 `images[]` 提交。
- 新增 `Zhenzhen Video G Omni Flash`、`Zhenzhen Video GK v1.5`、`Zhenzhen Video V3.1` 三个视频节点，V3.1 节点内合并 `zhenzhen-video-v31-fast` 与 `zhenzhen-video-v31-quality`。
- Zhenzhen Video 节点支持 prompt、时长、分辨率、画幅、可选反向提示词、seed 和最多 2 张参考图。
- 已真实验证本次新增 5 个模型均可提交、轮询完成并下载结果。

## v0.2.7（2026-07-21）

- 新增 Zhenzhen Image G-2 图像生成/编辑节点，支持 `zhenzhen-image-g2-t2i` 与 `zhenzhen-image-g2-i2i`。
- G-2 节点使用 `/v1/image/generations` 图片异步端点；`resolution` 固定为 `1k`，可选 `ratio`，图像编辑最多支持 10 张参考图。
- 新增 Zhenzhen Image G-2 文生图和图像编辑示例工作流，示例不保存 API Key、任务 ID、结果地址或运行缓存。
- 已真实验证 G-2 文生图和图像编辑可提交、轮询完成并下载结果。

## v0.2.6（2026-07-16）

- 新增 10 个 Vidu Q3、Hailuo 2.3 和 Kling 示例工作流，覆盖已真实跑通的文生视频、图生视频、首尾帧、参考生视频和视频编辑模式。
- Vidu 示例包含文生视频、图生视频和首尾帧；Hailuo 示例包含文生视频、标准图生视频和 Fast 图生视频。
- Kling 示例包含文生视频、图生视频/首尾帧、O3 参考生视频和 O3 视频编辑。
- 示例仅使用插件节点与 ComfyUI 核心加载/保存节点，API Key 保持空白，不保存任务 ID、结果地址或运行缓存。

## v0.2.5（2026-07-16）

- 新增 Kling 视频生成节点，合并接入 Kling 文生视频、图生视频/首尾帧和 O3 参考生视频模型。
- 新增 Kling O3 视频编辑节点，支持 `kling-o3-std-edit` 与 `kling-o3-pro-edit`，视频输入使用 `metadata.content[].video_url`。
- 已真实验证 `kling-v3.0-std-t2v`、`kling-v3.0-std-i2v`、`kling-o3-4k-r2v` 和 `kling-o3-std-edit` 可提交、轮询完成并下载结果。
- 当前实测 `kling-o3-std-r2v` / `kling-o3-pro-r2v` 提交阶段返回上游 502；`kling-elements-advanced` 需要额外的 frontal image element 结构；motion / lip-sync 属于特殊流程，暂不暴露为节点。

## v0.2.4（2026-07-16）

- 新增 Hailuo 2.3 视频生成节点，合并支持文生视频、图生视频和 fast 图生视频。
- 支持 `hailuo-2.3-t2v-standard`、`hailuo-2.3-t2v-pro`、`hailuo-2.3-i2v-standard`、`hailuo-2.3-i2v-pro`、`hailuo-2.3-fast-i2v`、`hailuo-2.3-fast-pro-i2v`。
- 已真实验证 6 个 Hailuo 2.3 模型均可提交、轮询完成并下载结果；图生视频首帧图短边需大于 300px。

## v0.2.3（2026-07-16）

- 新增 Vidu Q3 视频生成节点，合并接入文生视频、图生视频、首尾帧和参考生视频模型。
- 新增 Vidu Q3 短剧成片节点，接入 `vidu-q3-drama-short-play` 与 `vidu-q3-ad-short-play`，并上传参考资产图。
- 实测状态：`t2v`、`i2v`、`start-end` 已完成真实任务并下载结果；R2V 与短剧成片当前在提交阶段返回上游 `502 invalid_upstream_response`，待上游通道修复后复测。

## v0.2.2（2026-07-15）

- 新增 Zhenzhen Upscaler 视频超分节点，支持本地 `VIDEO` 自动上传或公网 MP4 直链，目标分辨率为 `720p`、`1080p`、`2k`、`4k`。

## v0.2.1（2026-07-14）

- 新增 Wan 2.7 Spicy 图生视频节点，支持首帧图、2 到 15 秒、720p / 1080p、可选音频 URL、反向提示词、提示词扩展与 seed。
- Seedream 图片节点新增 `model_family`，可在国内 `seedream-v5-pro` 与海外 `dola-seedream-5.0-pro` 之间切换。
- 新增 HappyHorse 1.1 文生视频、图生视频和参考图生视频示例工作流。
- 新增 Doubao Seed Audio 参考图识别人物和语音克隆示例工作流。
- 发布示例已移除任务 ID、结果地址和签名上传地址等运行缓存，不会改变节点或连线结构。

## v0.2.0（2026-07-13）

- 新增 HappyHorse 1.1 文生视频、图生视频和参考图生视频。
- 新增 Doubao Seed Audio 1.0 异步音频生成，支持音色 ID、参考图或最多 3 段参考音频。
- 新增 Seedream v5 Pro 文生图/图像编辑和最多 10 张参考图。
- 除 API 配置节点外，插件节点底部统一提供“获取平价版APIKEY”按钮，且不写入 workflow JSON。
- 保持既有节点注册键和输入输出顺序不变，旧工作流可继续加载。
- 已真实验证 Seed Audio 的模型发现、提交、轮询、WAV 下载和 ComfyUI `AUDIO` 解码链路。

## 功能特点

- 支持文生视频、图生视频、多模态视频
- 支持 Seedance 2.5 Standard 国内/海外文生、首尾帧图生和多模态参考生视频
- 支持 HappyHorse 1.1 文生视频、图生视频和参考图生视频
- 支持 Wan 2.7 Spicy 图生视频
- 接入 Kling 文生视频、图生视频、O3 参考生视频和 O3 视频编辑
- 支持 Hailuo 2.3 文生视频、图生视频和 fast 图生视频
- 支持 Hailuo H3 文生视频、首尾帧图生视频和多模态参考生视频
- 支持 FLUX 3 Video 国内/海外文生、最多 10 图关键帧图生、视频编辑和草稿增强
- 支持 MiniMax H3 OW Fast 单首帧图生视频和最多 9 图参考生视频
- 接入 Vidu Q3 文生视频、图生视频、首尾帧、参考生视频和短剧成片
- 支持 Zhenzhen Upscaler 视频超分
- 支持 Zhenzhen Video G / GK / V3.1 视频生成，V3.1 包含 Fast / Quality / Lite
- 支持国内 Seedream v5 Pro、海外 Dola Seedream 5.0 Pro 和 Zhenzhen Image G / GK / Nano Banana 文生图 / 图像编辑
- 支持 Doubao Seed Audio 1.0 异步音频生成
- 支持 Whisper 1 同步语音转写
- 支持 Suno 31 项音乐生成、引用、编辑、分轨、导出与分析操作
- 支持 Midjourney 16 项图片生成、编辑、二次操作、局部重绘和图生视频
- 支持图片 30 路、视频 10 路独立并发提交与按槽位接收，原节点仍可单独运行
- 图像编辑按节点支持最多 10 或 14 张参考图
- 除 `Seedance API Config` 外，插件节点底部统一提供“获取平价版APIKEY”按钮
- 内置 18 个 Seedance 2.0 模型变体
- 接入 6 个 Seedance 2.5 Standard 模型，并提供独立六合一节点
- 接入 3 个 HappyHorse 1.1 视频模型、1 个 Wan 2.7 Spicy 视频模型、21 个 Kling 视频/编辑模型、6 个 Hailuo 2.3 视频模型、6 个 Hailuo H3 视频模型、8 个 FLUX 3 Video 模型、5 个 MiniMax H3 OW 视频模型、15 个 Vidu Q3 模型、1 个 Zhenzhen Upscaler 视频超分模型、5 个 Zhenzhen Video 模型、2 个 Dola Seedream 图片模型、8 个 Qwen Image 3.0 图片模型、9 个 Zhenzhen Image G / GK / NB 图片模型、1 个 Doubao Seed Audio 模型、1 个 Whisper 转写模型和 31 项 Suno 操作
- 支持国内线路和 `global` 海外线路
- 支持 `standard`、`fast`、`mini` 三档模型
- 自动上传 IMAGE、VIDEO、AUDIO 参考素材
- 生成过程中显示 ComfyUI 进度条
- 生成完成后自动下载结果，视频输出为 `VIDEO`、图片输出为 `IMAGE`、音频输出为 `AUDIO`
- 支持 `skip_error`，批量工作流失败时可返回占位视频或静音音频
- API key 可来自配置节点、环境变量或本地 `config/.env`

## 节点列表

| 节点 | 用途 | 主要输入 |
| --- | --- | --- |
| `Seedance API Config` | API 连接配置 | `base_url`、`api_key` |
| `Seedance 文生视频 (Text to Video)` | 纯文本生成视频 | `model`、`prompt`、时长、分辨率、比例 |
| `Seedance 图生视频 (Image to Video)` | 首帧图生成视频，可选尾帧图 | `first_image`、可选 `last_image`、`prompt` |
| `Seedance 多模态视频 (Multimodal Video)` | 图片、视频、音频混合参考生成视频 | 最多 9 张图、3 个视频、3 段音频 |
| `Seedance 2.5 Standard 视频生成（6 合 1）` | 国内/海外 T2V、I2V、Multi 六模型统一调用 | 4 到 30 秒或智能时长、首尾帧、最多 30 图 10 视频 10 音频 |
| `Seedream / Dola Seedream 图像生成/编辑` | 国内 / 海外文生图和图像编辑；无参考图时使用 t2i，有参考图时使用 i2i | `model_family`、`prompt`、分辨率、输出格式、可选参考图 |
| `Qwen Image 3.0 / Pro 图像生成/编辑（8 合 1）` | 国内 / 海外标准版与 Pro 文生图、图像编辑 | `model`、`prompt`、尺寸模式、`n`、可选 1 到 3 张参考图 |
| `Zhenzhen Image G 图像生成/编辑` | G-2 / G v2 文生图和图像编辑；按 `model` 决定是否需要参考图 | `model`、`prompt`、`resolution=1k`、`ratio`、可选参考图 |
| `Zhenzhen Image GK v1.5 图像生成/编辑` | GK v1.5 文生图和图像编辑；编辑模型需要 `image1` | `model`、`prompt`、`size`、`n`、可选参考图 |
| `Zhenzhen Image Nano Banana 生成/编辑` | 4 个 Nano Banana 模型的文生图和最多 14 图参考编辑 | `model`、`prompt`、`resolution`、`size`、`n`、可选参考图 |
| `Zhenzhen Video G Omni Flash` | `zhenzhen-video-g-omni-flash` 视频生成 | `prompt`、时长、分辨率、比例、可选参考图 |
| `Zhenzhen Video GK v1.5` | `zhenzhen-video-gk-v15` 视频生成 | `prompt`、时长、分辨率、比例、可选参考图 |
| `Zhenzhen Video V3.1` | Fast / Quality / Lite 视频生成；Lite 仅文生视频 | `model`、`prompt`、固定 8 秒、分辨率、比例、按模型可选参考图 |
| `HappyHorse 1.1 视频生成` | `happyhorse-1.1-t2v` 文生视频、`happyhorse-1.1-i2v` 图生视频或 `happyhorse-1.1-r2v` 参考图生视频 | `model`、`prompt`、时长、分辨率、最多 9 张参考图 |
| `Wan 2.7 Spicy 图生视频` | `wan-2.7-spicy-i2v` 图生视频 | `first_image`、`prompt`、时长、分辨率、可选音频 URL |
| `Kling 视频生成` | Kling 文生视频、图生视频/首尾帧和 O3 参考生视频 | `model`、`prompt`、时长、比例、最多 4 张参考图 |
| `Kling O3 视频编辑` | Kling O3 视频编辑 | `video_url` 或 `input_video`、`prompt`、时长 |
| `Hailuo 2.3 视频生成` | Hailuo 2.3 文生视频、图生视频和 fast 图生视频 | `model`、`prompt`、时长、分辨率、首帧图 |
| `Hailuo H3 视频生成` | Hailuo H3 国内/海外文生、首尾帧图生和多模态参考生视频 | `model`、`prompt`、5 到 15 秒、768P/2K、按模型使用图片/视频/音频 |
| `FLUX 3 视频生成与草稿增强（8 合 1）` | FLUX 3 国内/海外 T2V、I2V、V2V 与 Draft Enhance | `model`、`prompt`、5 到 20 秒、HD/FHD、最多 10 图或一个视频、`draft_cache` |
| `MiniMax H3 OW 视频生成（3 合 1）` | MiniMax H3 OW 文生、图生和参考图生视频 | `model`、`prompt`、5/10/15 秒、480p/720p、可选参考图 |
| `MiniMax H3 OW Fast 视频生成（2 合 1）` | MiniMax H3 OW Fast 图生和多图参考生视频 | `model`、`prompt`、5/10/15 秒、480p/720p、1 到 9 张参考图 |
| `Vidu Q3 视频生成` | Vidu Q3 文生、图生、首尾帧和参考生视频 | `model`、`prompt`、时长、比例、可选参考图 |
| `Vidu Q3 短剧成片` | Vidu Q3 短剧 / 广告短片成片 | `model`、`prompt`、`script_name`、参考资产图 |
| `Zhenzhen Upscaler 视频超分` | `zhenzhen-upscaler` 视频超分 | `input_video` 或 `video_url`、目标分辨率 |
| `Doubao Seed Audio 1.0 音频生成` | 异步音频生成，使用 `/v1/audio/generations` | `prompt`、可选音色 ID / 参考图 / 最多 3 段参考音频 |
| `Whisper 1 语音转写` | 同步语音转写，使用 `/v1/audio/transcriptions` | `audio`、`response_format` |
| `Suno 音乐生成与处理（31 合 1）` | 音乐生成、素材导入、续写、翻唱、混合、编辑、分轨、导出与分析 | `operation` 和当前操作动态显示的输入 |
| `Midjourney 图像与视频（16 合 1）` | 图片生成、融合、描述、编辑、二次操作、局部重绘和图生视频 | `operation` 和当前操作动态显示的输入 |
| `并发提交｜...` | 使用对应原节点的完整参数异步提交图片或视频任务 | 与对应原节点相同 |
| `并发接收图片（30 路）` | 接收最多 30 个图片 Future，并按输入槽位输出图片 | `future_1` ... `future_30`、`failure_mode` |
| `并发接收视频（10 路）` | 接收最多 10 个视频 Future，并按输入槽位输出视频 | `future_1` ... `future_10`、`failure_mode` |

视频生成节点输出：

| 输出 | 说明 |
| --- | --- |
| `video` | 已下载到本地的结果视频，可继续连接保存或预览节点 |
| `video_url` | API 返回的视频直链 |
| `task_id` | 远端任务 ID |
| `response` | 完整 JSON 响应文本 |

图片节点输出：

| 输出 | 说明 |
| --- | --- |
| `image` | 已下载并转换为 ComfyUI `IMAGE` 的结果，可连接预览或保存节点 |
| `image_url` | API 返回的临时图片直链 |
| `task_id` | 远端图片任务 ID |
| `response` | 完整 JSON 响应文本 |

音频节点输出：

| 输出 | 说明 |
| --- | --- |
| `audio` | 已下载并转换为 ComfyUI `AUDIO` 的结果，可连接音频保存或后续处理节点 |
| `audio_url` | API 返回的临时音频直链 |
| `audio_path` | 已下载到本地输出目录的音频文件路径 |
| `task_id` | 远端音频任务 ID |
| `response` | 完整 JSON 响应文本 |

语音转写节点输出：

| 输出 | 说明 |
| --- | --- |
| `text` | 转写文本；`srt` / `vtt` / `text` 格式会直接返回对应文本 |
| `response` | 原始响应文本；`json` / `verbose_json` 格式会格式化为 JSON 字符串 |

Suno 节点输出：

| 输出 | 说明 |
| --- | --- |
| `audio1` / `audio2` | 前两条可解码音频结果 |
| `video` | `generate-mp4` 等操作返回的视频 |
| `text` | 歌词、标签、分析结果或可读摘要 |
| `primary_url` | 第一条主要结果地址 |
| `result_urls` | 全部识别结果地址的 JSON 数组 |
| `primary_path` | 第一条已转存结果的本地路径 |
| `result_paths` | 全部已转存结果路径的 JSON 数组 |
| `task_id` | 可直接连接后续 Suno 节点 |
| `response` | 完整 JSON 响应文本 |

Midjourney 节点输出：

| 输出 | 说明 |
| --- | --- |
| `image1` ... `image4` | 最多 4 张候选图片 |
| `grid_image` | 四宫格或合成预览图 |
| `video1` ... `video4` | 最多 4 路已下载视频 |
| `text` | Describe 文本或动作返回的可读文本 |
| `primary_url` | 第一条主要结果地址 |
| `result_urls` | 全部图片、四宫格和视频地址的 JSON 数组 |
| `primary_path` | 第一条已转存结果的本地路径 |
| `result_paths` | 与 `result_urls` 对齐的本地路径 JSON 数组 |
| `task_id` | 可直接连接后续 Midjourney 节点 |
| `buttons_json` | 服务端返回的可用按钮及 custom ID |
| `response` | 完整 JSON 响应文本 |

## 安装

进入 ComfyUI 的 `custom_nodes` 目录并克隆插件：

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/T8mars/ComfyUI_Seedance.git
```

使用 ComfyUI 对应的 Python 安装依赖：

```bash
cd ComfyUI
python -m pip install -r custom_nodes/ComfyUI_Seedance/requirements.txt
```

如果你使用的是 ComfyUI 便携包，请用便携包自带的 Python 执行安装命令。安装完成后重启 ComfyUI，节点会出现在 `Seedance` 分类下。

## API Key 配置

在 [api.seedance.nz/console](https://api.seedance.nz/console) 创建 API 令牌后，任选一种方式配置。

### 方式一：配置节点

添加 `Seedance API Config` 节点：

- `base_url`: `https://api.seedance.nz`
- `api_key`: 你的 API 令牌

然后把它的 `api_config` 输出连接到生成节点。

### 方式二：环境变量

Windows CMD：

```cmd
set SEEDANCE_API_KEY=your_api_key_here
```

PowerShell：

```powershell
$env:SEEDANCE_API_KEY = "your_api_key_here"
```

macOS / Linux：

```bash
export SEEDANCE_API_KEY=your_api_key_here
```

设置后再启动 ComfyUI。

### 方式三：本地 `.env`

在插件目录下创建 `config/.env`：

```env
SEEDANCE_API_KEY=your_api_key_here
SEEDANCE_BASE_URL=https://api.seedance.nz
```

`config/.env` 已被 `.gitignore` 忽略，适合本机长期使用。

## 快速开始

1. 添加 `Seedance API Config`，填写 API key。
2. 添加一个生成节点：
   - `Seedance 文生视频 (Text to Video)`：只用文本生成视频
   - `Seedance 图生视频 (Image to Video)`：用首帧图、可选尾帧图生成视频
   - `Seedance 多模态视频 (Multimodal Video)`：混合图片、视频、音频参考
   - `Seedance 2.5 Standard 视频生成（6 合 1）`：在国内/海外文生、图生与多模态六个模型间切换
   - `HappyHorse 1.1 视频生成`：在 `happyhorse-1.1-t2v`、`happyhorse-1.1-i2v` 和 `happyhorse-1.1-r2v` 间切换
   - `Wan 2.7 Spicy 图生视频`：连接首帧图，使用 `wan-2.7-spicy-i2v`
   - `Kling 视频生成`：在 Kling 文生、图生/首尾帧和 O3 参考生视频模型间切换
   - `Kling O3 视频编辑`：连接 `input_video` 或填写公网 MP4 `video_url`
   - `Hailuo 2.3 视频生成`：在 Hailuo 文生视频、图生视频和 fast 图生视频模型间切换
   - `Hailuo H3 视频生成`：在 H3 文生、首尾帧图生和多模态参考生视频模型间切换
   - `Vidu Q3 视频生成`：在 Vidu 文生、图生、首尾帧和参考生视频模型间切换
   - `Vidu Q3 短剧成片`：填写短剧脚本内容、`script_name`，并连接至少 1 张参考资产图
   - `Zhenzhen Video G Omni Flash`：使用 `zhenzhen-video-g-omni-flash`
   - `Zhenzhen Video GK v1.5`：使用 `zhenzhen-video-gk-v15`
   - `Zhenzhen Video V3.1`：在 `zhenzhen-video-v31-fast`、`zhenzhen-video-v31-quality` 和仅文生视频的 `zhenzhen-video-v31-lite` 间切换
   - `Zhenzhen Upscaler 视频超分`：连接 `input_video` 或填写公网 MP4 `video_url`
3. 选择 `model`，设置 `seconds`、`resolution`、`ratio`。
4. 运行工作流。
5. 将 `video` 输出连接到 `SaveVideo` 或其他视频节点。

图片或视频并发生成：

1. 添加多个名称以 `并发提交｜` 开头的生成节点；它们保留对应原节点的参数和素材输入。
2. 图片提交节点连接 `并发接收图片（30 路）`，视频提交节点连接 `并发接收视频（10 路）`。
3. 将各提交节点的 `future` 按需要连接到接收节点的 `future_1`、`future_2` 等插槽。
4. 接收节点会并行等待并按插槽顺序输出。`failure_mode=raise` 会在失败时停止并指出槽位；`placeholder` 会保留其他成功槽，并在 `status_json` 中给出脱敏状态。
5. 不需要并发时继续使用原节点即可；旧工作流无需迁移。

并发接收节点按媒体类型通用，并不限制模型。示例中的 GK v1.5 只是演示用节点，可以替换或混合连接下列提交节点：

| 接收节点 | 可连接的并发提交节点 |
| --- | --- |
| `并发接收图片（30 路）` | Seedream / Dola Seedream、Zhenzhen Image G、GK v1.5、Nano Banana、Midjourney 图片 |
| `并发接收视频（10 路）` | Seedance 文生/图生/多模态、Zhenzhen Video G/GK/V3.1、HappyHorse、Wan、Kling、Hailuo、Vidu、Upscaler、Midjourney 视频 |

不同原节点的输入参数和素材类型不同，所以每个原节点都有对应的 `并发提交｜...` 版本；它们输出统一的图片 Future 或视频 Future。同类型 Future 可以混接到同一个接收节点，例如 `Seedream future -> future_1`、`Image G future -> future_2`、`Nano Banana future -> future_3`。

图片生成或编辑：

1. 添加 `Seedream / Dola Seedream 图像生成/编辑`。
2. 填写 5 到 2000 字符的 `prompt`。
3. 选择 `model_family`：国内 `seedream-v5-pro` 或海外 `dola-seedream-5.0-pro`。
4. 不连接参考图时执行文生图；连接 `image1` 到 `image10` 中任意参考图时执行图像编辑。
5. 选择 `1k`、`2k`，或选择 `custom` 后设置 `width` 和 `height`。
6. 将 `image` 输出连接到 `Preview Image` 或 `Save Image`。

Zhenzhen Image G 图片生成或编辑：

1. 添加 `Zhenzhen Image G 图像生成/编辑`。
2. 默认使用 `zhenzhen-image-g-v2-lowprice`；也可切换到 `zhenzhen-image-g2-t2i` 或 `zhenzhen-image-g2-i2i`。
3. Lowprice 可选择 `1k`、`2k`、`4k`，并设置 `size` 与 `n`；G-2 固定 `1k`，按需选择 `ratio`。
4. `zhenzhen-image-g2-i2i` 需要连接 1 到 10 张参考图；Lowprice 可不连接图，也可连接最多 16 张参考图。
5. 将 `image` 输出连接到 `Preview Image` 或 `Save Image`。

Zhenzhen Image GK v1.5 图片生成或编辑：

1. 添加 `Zhenzhen Image GK v1.5 图像生成/编辑`。
2. 选择 `zhenzhen-image-gk-v15` 生成图片，或选择 `zhenzhen-image-gk-v15-edit` 编辑参考图。
3. 填写提示词，选择 `size`，按需设置 `n`。
4. 使用编辑模型时连接 `image1`；节点会按文档只提交第一张参考图。
5. 将 `image` 输出连接到 `Preview Image` 或 `Save Image`。

Zhenzhen Image Nano Banana 图片生成或编辑：

1. 添加 `Zhenzhen Image Nano Banana 生成/编辑`。
2. 在 Flash、NB 2、NB 2 Lite 和 NB Pro 四个模型间切换；分辨率、比例和图片数量会随模型自动调整。
3. 填写提示词；不连接参考图时执行文生图，连接 `image1` 到 `image14` 时执行图像编辑。
4. `nb-flash` 固定 1k；`nb-2` 支持 0.5k 到 4k；`nb-2-lite` 固定 1k 且 `n` 可为 1 到 4；`nb-pro` 支持 1k、2k、4k。
5. 将 `image` 输出连接到 `Preview Image` 或 `Save Image`。

音频生成：

1. 添加 `Doubao Seed Audio 1.0 音频生成`。
2. 填写 5 到 2048 字符的 `prompt`。
3. 可选填写 `speaker` 音色 ID，或连接 1 张参考图，或连接最多 3 段参考音频；三类来源互斥。
4. 建议先使用默认 `wav` 输出，最容易被 ComfyUI 解码。
5. 将 `audio` 输出连接到音频保存、预览或后续处理节点。

语音转写：

1. 添加 `Whisper 1 语音转写`。
2. 连接 ComfyUI `AUDIO` 输入，节点会自动转换为 wav 并通过 multipart 提交。
3. 选择 `response_format`，默认 `json` 会输出普通转写文本和格式化响应。
4. 将 `text` 输出连接到文本展示、字幕处理或后续提示词节点。

Suno 音乐生成与处理：

1. 添加 `Suno 音乐生成与处理（31 合 1）`，选择 `operation`。
2. 音乐生成、歌词、音效和风格标签操作直接填写当前显示的文本字段。
3. 素材导入、创建音色和参考生成可连接本地 `AUDIO` 或填写公网音频 URL；导入源音频至少 6 秒。
4. 续写、翻唱、编辑、分轨和导出可把前一个 Suno 节点的 `task_id` 直接连接过来；翻唱、双曲混合、采样和三项添加动作还需填写 `prompt`，双曲混合连接两个任务。
5. 按结果类型连接 `audio1`、`video` 或 `text`，其余结果可从 URL、路径和完整响应输出读取。

Midjourney 图片与视频：

1. 添加 `Midjourney 图像与视频（16 合 1）`，选择 `operation`，节点会自动收起无关控件。
2. Imagine / Edits 直接填写或连接 `prompt`；Blend / Describe / Edits 可连接本地 `IMAGE` 或填写同槽公网图片 URL。
3. Upscale、Variation、Reroll、Zoom、Pan、Inpaint 和 Remix 可直接连接前一个 Midjourney 节点的 `task_id`。
4. 普通图片二次操作的 `index` 使用 1 到 4；任务复用视频的 `index` 使用 0 到 3。也可从 `buttons_json` 取得 custom ID。
5. 局部重绘先运行 Inpaint，待其到达 `MODAL` 后连接到 Modal；当前请使用已实测成功的 `region` 模式并连接 ComfyUI `MASK`。文档所述无 mask `outpaint` 目前会被上游拒绝。
6. 按动作连接图片、视频或文本输出；完整示例已覆盖参考图、任务复用视频和首尾帧视频。

示例工作流位于：

- `examples/seedance_text_to_video.json`
- `examples/seedance_image_to_video.json`
- `examples/seedance_multimodal_video.json`
- `examples/seedance-2.5-*.json`（6 份，覆盖国内/海外 T2V、I2V、Multi）
- `examples/flux-3-video-*.json`（8 份，覆盖国内/海外 T2V、I2V、V2V、Draft Enhance）
- `examples/海螺hailuo-h3*.json`（6 份，覆盖国内/海外 T2V、I2V、Multi）
- `examples/seedream-v5-pro-图像编辑和文生图.json`
- `examples/seedream-v5-pro图层拆分.json`
- `examples/seedream-v5-pro宽审核文生图.json`
- `examples/seedream-v5-pro宽审核图像编辑.json`
- `examples/zhenzhen-image-g2文生图.json`
- `examples/zhenzhen-image-g2图像编辑.json`
- `examples/zhenzhen-image-g-v2-lowprice文生图.json`
- `examples/zhenzhen-image-g-v2-lowprice图像编辑.json`
- `examples/zhenzhen-image-gk-v15文生图.json`
- `examples/zhenzhen-image-gk-v15图像编辑.json`
- `examples/zhenzhen-image-nb-*.json`（8 份，4 个模型各含文生图和图像编辑）
- `examples/zhenzhen-video-g-omni-flash文生视频.json`
- `examples/zhenzhen-video-g-omni-flash图生视频.json`
- `examples/zhenzhen-video-gk-v15文生视频.json`
- `examples/zhenzhen-video-gk-v15图生视频.json`
- `examples/zhenzhen-video-v31-fast文生视频.json`
- `examples/zhenzhen-video-v31-fast图生视频.json`
- `examples/zhenzhen-video-v31-quality文生视频.json`
- `examples/zhenzhen-video-v31-quality图生视频.json`
- `examples/zhenzhen-video-v31-lite文生视频.json`
- `examples/wan2.7图生视频宽审核.json`
- `examples/zhenzhen-video-upscaler-视频高清化.json`
- `examples/快乐马happy-horse-1.1文生视频.json`
- `examples/快乐马happy-horse-1.1图生视频.json`
- `examples/快乐马happy-horse-1.1参考生视频.json`
- `examples/seed-audio-1.0音频生成（识别图片人物）.json`
- `examples/seed-audio-1.0音频生成（语音克隆）.json`
- `examples/whisper-1语音转写.json`
- `examples/suno-*.json`（31 份，每个 operation 一份）
- `examples/midjourney-*.json`（19 份，覆盖全部 16 个 operation 和 3 个常用变体）
- `examples/vidu-q3文生视频.json`
- `examples/vidu-q3图生视频.json`
- `examples/vidu-q3首尾帧视频.json`
- `examples/海螺hailuo-2.3文生视频.json`
- `examples/海螺hailuo-2.3图生视频.json`
- `examples/海螺hailuo-2.3-fast图生视频.json`
- `examples/海螺hailuo-h3文生视频.json`
- `examples/海螺hailuo-h3图生视频首尾帧.json`
- `examples/海螺hailuo-h3多模态参考生视频.json`
- `examples/可灵kling-v3.0文生视频.json`
- `examples/可灵kling-v3.0图生视频首尾帧.json`
- `examples/可灵kling-o3参考生视频.json`
- `examples/可灵kling-o3视频编辑.json`
- `examples/并发图片2路最小验证.json`
- `examples/并发视频2路最小验证.json`
- `examples/并发图片30路示例.json`
- `examples/并发视频10路示例.json`

可以直接把 JSON 文件拖进 ComfyUI 加载。

## 模型选择

每个生成节点提供 6 个对应任务类型的模型：

| 档位 | 国内线路 | 海外线路 |
| --- | --- | --- |
| Standard | `seedance-2.0-standard-*` | `seedance-2.0-global-standard-*` |
| Fast | `seedance-2.0-fast-*` | `seedance-2.0-global-fast-*` |
| Mini | `seedance-2.0-mini-*` | `seedance-2.0-global-mini-*` |

`*` 由节点类型决定：

- `t2v`：文生视频
- `i2v`：图生视频
- `multi`：多模态视频

Seedance 2.5 使用独立的六合一节点，仅包含 Standard 国内/海外线路：

| 任务 | 国内线路 | 海外线路 |
| --- | --- | --- |
| 文生视频 | `seedance-2.5-standard-t2v` | `seedance-2.5-global-standard-t2v` |
| 图生视频 | `seedance-2.5-standard-i2v` | `seedance-2.5-global-standard-i2v` |
| 多模态视频 | `seedance-2.5-standard-multi` | `seedance-2.5-global-standard-multi` |

该节点支持 4 到 30 秒；选择 `-1` 时按接口要求提交 `metadata.duration=-1`。I2V 使用 1 到 2 张首尾帧图片；Multi 将图片、视频、音频统一写入 `metadata.content`。

图片节点使用独立的 `/v1/image/generations` 端点。`model_family` 决定模型族，不连接参考图时提交 t2i，连接参考图时提交 i2i：

| `model_family` | 文生图 | 图像编辑 |
| --- | --- | --- |
| `seedream-v5-pro (domestic)` | `seedream-v5-pro-t2i` | `seedream-v5-pro-i2i` |
| `dola-seedream-5.0-pro (overseas)` | `dola-seedream-5.0-pro-t2i` | `dola-seedream-5.0-pro-i2i` |

Qwen Image 3.0 节点使用独立的 `/v1/image/generations` 图片端点：

| 线路与版本 | 文生图 | 图像编辑 |
| --- | --- | --- |
| 国内标准版 | `qwen-image-3.0-t2i` | `qwen-image-3.0-i2i` |
| 国内 Pro | `qwen-image-3.0-pro-t2i` | `qwen-image-3.0-pro-i2i` |
| 海外标准版 | `qwen-image-3.0-global-t2i` | `qwen-image-3.0-global-i2i` |
| 海外 Pro | `qwen-image-3.0-global-pro-t2i` | `qwen-image-3.0-global-pro-i2i` |

图像编辑模型必须连接 1 到 3 张参考图。`auto` 尺寸模式不发送尺寸；`ratio` 模式发送画幅与 `1k`/`2k`；`custom_size` 模式发送 `W*H` 自定义尺寸。

Zhenzhen Image G 节点使用独立的 `/v1/image/generations` 图片端点：

| 模型 | 用途 | 限制 |
| --- | --- | --- |
| `zhenzhen-image-g2-t2i` | 文生图 | `prompt` 必填；`resolution` 固定为 `1k`；可选 `ratio` |
| `zhenzhen-image-g2-i2i` | 图像编辑 | 需要 1 到 10 张参考图；`prompt` 必填；`resolution` 固定为 `1k`；可选 `ratio` |
| `zhenzhen-image-g-v2-lowprice` | 文生图 / 图像编辑 | 默认模型；`resolution` 为 `1k` / `2k` / `4k`；顶层 `size` 支持比例或 WxH；`n` 为 1 到 10；参考图最多 16 张 |

Zhenzhen Image GK v1.5 节点使用同一个 `/v1/image/generations` 图片端点：

| 模型 | 用途 | 参数 |
| --- | --- | --- |
| `zhenzhen-image-gk-v15` | 文生图 | `prompt` 必填；`size` 为 `1:1`、`16:9`、`9:16`、`3:2` 或 `2:3`；`n` 为 1 到 10 |
| `zhenzhen-image-gk-v15-edit` | 图像编辑 | `prompt` 必填；`image1` 必填且只提交第一张；`size` 和 `n` 使用同上 |

Zhenzhen Image Nano Banana 节点使用同一个 `/v1/image/generations` 图片端点：

| 模型 | 分辨率 | 数量 | 参考图与比例 |
| --- | --- | --- | --- |
| `zhenzhen-image-nb-flash` | 固定 `1k` | 固定 `1` | 最多 14 张；支持 `auto` 与常用比例；提示词最多 1000 字符 |
| `zhenzhen-image-nb-2` | `0.5k` / `1k` / `2k` / `4k` | 固定 `1` | 最多 14 张；支持 `1:4`、`4:1`、`1:8`、`8:1` 等扩展比例 |
| `zhenzhen-image-nb-2-lite` | 固定 `1k` | `1` 到 `4` | 最多 14 张；支持扩展比例 |
| `zhenzhen-image-nb-pro` | `1k` / `2k` / `4k` | 固定 `1` | 最多 14 张；支持常用比例 |

Zhenzhen Video 节点使用 `/v1/videos` 视频端点：

| 节点 | 模型 | 素材 |
| --- | --- | --- |
| `Zhenzhen Video G Omni Flash` | `zhenzhen-video-g-omni-flash` | 可选 `image1` / `image2` |
| `Zhenzhen Video GK v1.5` | `zhenzhen-video-gk-v15` | 可选 `image1` / `image2` |
| `Zhenzhen Video V3.1` | `zhenzhen-video-v31-fast` / `zhenzhen-video-v31-quality` / `zhenzhen-video-v31-lite` | Fast 最多 3 图；Quality 最多 2 图；Lite 禁止图片 |

Whisper 节点使用同步 `/v1/audio/transcriptions` 转写端点：

| 模型 | 输入 | 输出 |
| --- | --- | --- |
| `whisper-1` | ComfyUI `AUDIO`，节点转换为 wav multipart 文件 | `text` 和原始响应 |

Suno 节点使用独立的音乐接口：

- `suno-generation` 提交到 `POST /v1/music/generations`。
- 其余操作提交到显式的 `POST /v1/music/generations/{action}`。
- 异步任务通过 `GET /v1/music/tasks/{task_id}` 查询到最终状态。
- 请求体中的 `model` 固定为 `suno`，`operation` 只用于选择 action。
- 节点按操作执行字段白名单，隐藏字段不会进入请求。
- 真实接口确认 `suno-cover-song`、`suno-mashup`、`suno-sample`、`suno-add-vocals`、`suno-add-instrumental` 和 `suno-add-stem` 在默认模式下还需要 `prompt`。

HappyHorse 节点使用同一个 `/v1/videos` 视频端点：

| 模型 | 用途 | 限制 |
| --- | --- | --- |
| `happyhorse-1.1-t2v` | 文生视频 | `prompt` 必填，`seconds` 为 3 到 15 秒，不支持 `-1` |
| `happyhorse-1.1-i2v` | 图生视频 | 必须连接 `first_image`，只使用首张图；`prompt` 可选 |
| `happyhorse-1.1-r2v` | 参考图生视频 | `first_image` 作为图1，`reference_image2` 到 `reference_image9` 作为图2到图9；至少 1 张，最多 9 张；`prompt` 可写“图1/图2” |

HappyHorse 仅支持 `720p` 和 `1080p`，`ratio` 会作为 `metadata.ratio` 传入，由 API 映射到上游 `aspectRatio`。

Wan 2.7 Spicy 节点使用 `/v1/videos` 视频端点：

| 模型 | 用途 | 限制 |
| --- | --- | --- |
| `wan-2.7-spicy-i2v` | 图生视频 | `images[0]` 必填；`seconds` 为 2 到 15 秒；`resolution` 为 `720p` 或 `1080p`；可选 `prompt` / `audio_url` / `negative_prompt` / `prompt_extend` / `seed` |

Kling 视频节点使用 `/v1/videos` 视频端点：

| 模型 | 用途 | 素材 |
| --- | --- | --- |
| `kling-v3.0-std-t2v` / `kling-v3.0-pro-t2v` / `kling-v3-turbo-std-t2v` / `kling-v3-turbo-pro-t2v` / `kling-v3-4k-t2v` / `kling-o3-std-t2v` / `kling-o3-pro-t2v` / `kling-o3-4k-t2v` | 文生视频 | `prompt` 必填 |
| `kling-v3.0-std-i2v` / `kling-v3.0-pro-i2v` / `kling-v3-turbo-std-i2v` / `kling-v3-turbo-pro-i2v` / `kling-v3-4k-i2v` / `kling-o3-std-i2v` / `kling-o3-pro-i2v` / `kling-o3-4k-i2v` | 图生视频 / 首尾帧 | `image1` 必填，可选 `image2` 作为尾帧 |
| `kling-o3-std-r2v` / `kling-o3-pro-r2v` / `kling-o3-4k-r2v` | O3 参考生视频 | `image1` 到 `image4`，按连接顺序提交；当前仅 `kling-o3-4k-r2v` 已真实跑通，std/pro 提交阶段上游返回 502 |
| `kling-o3-std-edit` / `kling-o3-pro-edit` | O3 视频编辑 | 使用独立编辑节点，视频直链写入 `metadata.content[].video_url` |

Kling 普通视频支持 5 或 10 秒；`ratio` 非 `adaptive` 时透传为 `metadata.ratio`。`kling-v3.0-std-motion` / `kling-v3.0-pro-motion` / `kling-v3.0-4k-motion`、`kling-elements-advanced` 和 lip-sync 系列需要特殊结构或多步流程，当前不暴露为可用节点。

Hailuo 2.3 节点使用 `/v1/videos` 视频端点：

| 模型 | 用途 | 素材 |
| --- | --- | --- |
| `hailuo-2.3-t2v-standard` / `hailuo-2.3-t2v-pro` | 文生视频 | `prompt` 必填 |
| `hailuo-2.3-i2v-standard` / `hailuo-2.3-i2v-pro` | 图生视频 | `first_image` 作为 `images[0]` |
| `hailuo-2.3-fast-i2v` / `hailuo-2.3-fast-pro-i2v` | fast 图生视频 | `first_image` 作为 `images[0]` |

Hailuo 2.3 支持 6 或 10 秒，`1080p` 仅支持 6 秒；图生视频首帧图短边需大于 300px，宽高比需在 2:5 到 5:2 之间。文生视频会把 `ratio` 透传为 `metadata.ratio`；图生视频跟随输入图片比例。

Hailuo H3 节点使用 `/v1/videos` 视频端点：

| 模型 | 用途 | 素材 |
| --- | --- | --- |
| `hailuo-h3-t2v` / `hailuo-h3-global-t2v` | 国内/海外文生视频 | `prompt` 必填，不使用参考素材 |
| `hailuo-h3-i2v` / `hailuo-h3-global-i2v` | 国内/海外图生视频 / 首尾帧 | `image1` 必填首帧，`image2` 可选尾帧 |
| `hailuo-h3-multi` / `hailuo-h3-global-multi` | 国内/海外多模态参考生视频 | 最多 9 张图、3 个视频、3 段音频，至少连接一种素材 |

Hailuo H3 分辨率支持 `768P` 或 `2K`，时长支持 5 到 15 秒。T2V 与 Multi 会提交 `metadata.ratio`；I2V 跟随输入帧，不提交比例。Multi 的三类本地素材会自动上传，并分别映射到图片、视频和音频参考字段。

FLUX 3 Video 节点使用 `/v1/videos` 视频端点：

| 模型组 | 用途 | 素材 |
| --- | --- | --- |
| `flux-3-video-[global-]t2v` | 国内/海外文生视频 | `prompt` 必填 |
| `flux-3-video-[global-]i2v` | 国内/海外关键帧图生视频 | `image1` 必填，最多连接 `image1` 到 `image10` |
| `flux-3-video-[global-]v2v` | 国内/海外视频编辑 | `input_video` 或 `video_url` 二选一，`prompt` 必填 |
| `flux-3-video-[global-]draft-enhance` | 国内/海外草稿增强 | 连接同线路草稿任务输出的 `draft_cache` |

八个模型均支持 5 到 20 秒、`hd` / `fhd` 与 `auto`、`21:9`、`2:1`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16` 比例。开启 `draft` 的普通生成会输出可直接连接 Draft Enhance 的 `draft_cache`；`audio_mode=api_default` 和 `safety_tolerance=api_default` 时不发送对应可选字段。

MiniMax H3 OW 节点使用 `/v1/videos` 视频端点：

| 模型 | 用途 | 素材 |
| --- | --- | --- |
| `minimax-h3-ow-t2v` | 文生视频 | `prompt` 必填，不使用图片 |
| `minimax-h3-ow-i2v` | 图生视频 | `image1` 必填，`prompt` 可选 |
| `minimax-h3-ow-r2v` | 参考图生视频 | `image1` 与 `prompt` 必填 |

三个模型均支持 5、10、15 秒，分辨率为 `480p` 或 `720p`；画幅支持 `1:1`、`2:3`、`3:2`、`3:4`、`4:3`、`9:16`、`16:9`、`21:9`。

MiniMax H3 OW Fast 使用独立二合一节点和相同的视频端点：

| 模型 | 用途 | 素材 |
| --- | --- | --- |
| `minimax-h3-ow-i2v-fast` | Fast 图生视频 | 必须且只能连接 `image1`，`prompt` 可选 |
| `minimax-h3-ow-r2v-fast` | Fast 参考生视频 | `prompt` 必填，支持 `image1` 到 `image9` |

两个 Fast 模型同样支持 5、10、15 秒、`480p` / `720p` 与上述 8 种画幅。前端会在 I2V 模式仅显示首帧，在 R2V 模式显示全部 9 个参考图插槽。

Vidu Q3 节点使用 `/v1/videos` 视频端点：

| 模型 | 用途 | 素材 |
| --- | --- | --- |
| `vidu-q3-pro-t2v` / `vidu-q3-turbo-t2v` / `vidu-q3-pro-fast-t2v` | 文生视频 | 仅 `prompt` |
| `vidu-q3-pro-i2v` / `vidu-q3-turbo-i2v` / `vidu-q3-pro-fast-i2v` | 图生视频 | `image1` 作为首帧图 |
| `vidu-q3-pro-start-end` / `vidu-q3-turbo-start-end` / `vidu-q3-pro-fast-start-end` | 首尾帧视频 | `image1` + `image2` |
| `vidu-q3-r2v` / `vidu-q3-mix-r2v` / `vidu-q3-ad-r2v` / `vidu-q3-drama-r2v` | 参考生视频 | `image1` 到 `image9`，按连接顺序提交；当前实测提交阶段上游返回 502 |
| `vidu-q3-drama-short-play` / `vidu-q3-ad-short-play` | 短剧成片 | 使用独立短剧节点，`prompt` 为脚本内容，`script_name` 透传为 `metadata.script_name`，并通过 `asset_image1` 到 `asset_image14` 上传参考资产；当前实测提交阶段上游返回 502 |

Vidu 普通视频节点会把 `ratio` 透传为 `metadata.ratio`；`resolution=default` 时不提交分辨率字段，使用 API 默认值。

Zhenzhen Upscaler 节点使用 `/v1/videos` 视频端点：

| 模型 | 用途 | 限制 |
| --- | --- | --- |
| `zhenzhen-upscaler` | 视频超分 | `metadata.content` 恰好 1 条 `video_url`；`resolution` 为 `720p`、`1080p`、`2k` 或 `4k`；可连接本地 `VIDEO` 自动上传，也可直接填写公网 MP4 直链 |

Doubao Seed Audio 节点使用独立的 `/v1/audio/generations` 异步端点，不是 `/v1/audio/speech`。成功后从 `data.result_url` 或 `data.data.content.audio_url` 读取音频直链。

建议第一次测试先用短时长、低分辨率，确认连通和输出格式后再切换高规格模型。

## 随机种子与缓存

- 所有生成与处理节点都有 `seed` 及其运行后控制选项。新节点默认使用 `randomize`，每次运行后自动换种子并重新执行。
- 选择 `fixed` 后，只要节点全部输入和上游输入都没有变化，ComfyUI 会直接复用缓存结果，不会再次提交任务。
- `increment`、`decrement` 和 `randomize` 会在运行后改变种子，因此下一次运行会产生新的执行；手动修改任一其他参数也会使缓存失效。
- 模型原生支持种子时，节点继续按该模型既有规则传递种子；没有文档种子参数的模型仅把它作为本地缓存键，不会把额外字段加入请求。
- 清空 ComfyUI 缓存或重启后，之前的缓存结果可能不再可用。旧工作流没有保存运行后控制状态时会自动使用 `randomize`，原有参数和连线不变。

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `model` | 当前任务类型下的 Seedance 模型 |
| `prompt` | 提示词，最多 20480 字符 |
| `seconds` | 视频时长，4 到 15 秒；`-1` 表示由模型决定 |
| `resolution` | `480p`、`720p`、`1080p`、`2k`、`4k`、`native1080p`、`native4k` |
| `ratio` | `adaptive`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16`、`21:9` |
| `generate_audio` | 是否生成配音、音效或音频 |
| `seed` | 模型原生支持时按既有规则透传；其他节点仅用于 ComfyUI 缓存判断 |
| `api_config` | 可选，连接 `Seedance API Config` 节点 |
| `skip_error` | 开启后失败时返回占位结果，而不是中断整个工作流 |

`native1080p` 和 `native4k` 仅支持 Standard 档模型，插件会在提交前校验。

`1080p`、`2k`、`4k` 属于从 720p 超分的输出档位。

图片节点参数：

| 参数 | 说明 |
| --- | --- |
| `prompt` | 必填，5 到 2000 字符 |
| `resolution` | `1k`、`2k` 或 `custom`；选择预设时 API 会忽略宽高 |
| `width` / `height` | 仅 `custom` 时提交，范围 240 到 8192 |
| `output_format` | `png` 或 `jpeg` |
| `model_family` | 国内 `seedream-v5-pro` 或海外 `dola-seedream-5.0-pro` |
| `image1` ... `image10` | 可选参考图；未连接时文生图，连接后图像编辑 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |

Seedream 图层拆分节点参数与输出：

| 参数/输出 | 说明 |
| --- | --- |
| `image` | 必填，恰好 1 张待拆分图片；节点自动上传 |
| `prompt` | 可选拆分要求，0 到 2000 字符 |
| `resolution` | `auto`、`1k`、`1.5k` 或 `2k` |
| `output_format` | `png` 或 `jpeg`；需要透明图层时建议使用 PNG |
| `images` / `masks` | 按 API 顺序输出的 ComfyUI 列表；第 1 项为底图，后续为全部图层及其透明 MASK |
| `image_urls` / `image_count` | 完整结果 URL 数组 JSON 与实际结果数量 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |

Qwen Image 3.0 参数：

| 参数 | 说明 |
| --- | --- |
| `model` | 8 个国内 / 海外标准版与 Pro T2I/I2I 模型 |
| `prompt` | 必填，5 到 2000 字符 |
| `negative_prompt` / `prompt_extend` | 可选负面提示词与提示词扩写开关 |
| `sizing_mode` | `auto`、`ratio` 或 `custom_size`；三种请求结构互斥 |
| `resolution` / `ratio` | 仅 `ratio` 模式发送；分辨率为 `1k` 或 `2k` |
| `custom_size` | 仅 `custom_size` 模式发送，例如 `1024*1024` |
| `n` / `seed` | 图片数量 1 到 6；`seed=-1` 时不发送 seed |
| `image1` ... `image3` | 仅 I2I 使用，至少 1 张、最多 3 张 |

Zhenzhen Image G 参数：

| 参数 | 说明 |
| --- | --- |
| `model` | 默认 `zhenzhen-image-g-v2-lowprice`；也可选择两个 G-2 模型 |
| `prompt` | 必填，最多 20000 字符 |
| `resolution` | G-2 固定 `1k`；Lowprice 支持 `1k` / `2k` / `4k` |
| `ratio` | 仅 G-2 使用；`adaptive` 时不提交 |
| `size` / `custom_size` | 仅 Lowprice 使用；常用比例下拉，选择 `custom` 后可填写比例或 `WxH` |
| `n` | 仅 Lowprice 使用；1 到 10 |
| `image1` ... `image16` | G-2 图像编辑使用前 10 张且至少 1 张；Lowprice 最多 16 张且可不连接 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |

Zhenzhen Image GK v1.5 参数：

| 参数 | 说明 |
| --- | --- |
| `model` | `zhenzhen-image-gk-v15` 或 `zhenzhen-image-gk-v15-edit` |
| `prompt` | 必填，最多 20000 字符 |
| `size` | `1:1`、`16:9`、`9:16`、`3:2` 或 `2:3` |
| `n` | 1 到 10，节点下载网关返回的主结果 |
| `image1` | 编辑模型必填；文生图模型不使用 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |

Zhenzhen Image Nano Banana 参数：

| 参数 | 说明 |
| --- | --- |
| `model` | `zhenzhen-image-nb-flash`、`zhenzhen-image-nb-2`、`zhenzhen-image-nb-2-lite` 或 `zhenzhen-image-nb-pro` |
| `prompt` | 必填；`nb-flash` 最多 1000 字符 |
| `resolution` | 按模型动态限制为 `0.5k`、`1k`、`2k`、`4k` 的可用子集 |
| `size` | 按模型动态限制；NB 2 / NB 2 Lite 支持扩展比例 |
| `n` | 仅 NB 2 Lite 支持 1 到 4；其余模型固定为 1 |
| `image1` ... `image14` | 可选参考图；未连接时文生图，连接后按槽位顺序提交图像编辑 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |

Zhenzhen Video G / GK / V3.1 参数：

| 参数 | 说明 |
| --- | --- |
| `model` | 当前节点支持的 Zhenzhen 视频模型；V3.1 节点可在 fast / quality / lite 间切换 |
| `prompt` | 必填，最多 20480 字符 |
| `seconds` | 通用节点为 4 到 15 秒，GK v1.5 为 6 到 30 秒；V3.1 固定为 8 秒 |
| `resolution` | 通用节点为 `720p` / `1080p`；V3.1 另支持 `4k` |
| `ratio` | 通用节点支持可选画幅；V3.1 仅支持 `16:9` / `9:16` |
| `negative_prompt` | 可选反向提示词，透传为 `metadata.negative_prompt` |
| `seed` | `-1` 为随机种子；非负整数透传为 `metadata.seed` |
| `image1` / `image2` / `image3` | 通用节点最多 2 图；V3.1 Fast 最多 3 图，Quality 最多 2 图，Lite 禁止图片 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |

HappyHorse 节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | `happyhorse-1.1-t2v`、`happyhorse-1.1-i2v` 或 `happyhorse-1.1-r2v` |
| `prompt` | 文生视频必填，图生视频/参考图生视频可选；r2v 可用“图1/图2”引用参考图 |
| `seconds` | 3 到 15 秒，不支持 `-1` |
| `resolution` | `720p` 或 `1080p` |
| `ratio` | 画幅比例，透传为 `metadata.ratio` |
| `first_image` | `happyhorse-1.1-i2v` 必填；`happyhorse-1.1-r2v` 中作为图1 |
| `reference_image2` ... `reference_image9` | 仅 `happyhorse-1.1-r2v` 使用，可选参考图2到图9 |

Wan 2.7 Spicy 节点参数：

| 参数 | 说明 |
| --- | --- |
| `first_image` | 必填首帧图，作为 `images[0]` 提交 |
| `prompt` | 可选提示词，最多 20480 字符 |
| `seconds` | 2 到 15 秒 |
| `resolution` | `720p` 或 `1080p` |
| `negative_prompt` | 可选反向提示词，透传为 `metadata.negative_prompt` |
| `audio_url` | 可选公网音频 URL，透传为 `metadata.audio_url` |
| `prompt_extend` | 可选提示词扩展开关，透传为 `metadata.prompt_extend` |
| `seed` | `-1` 为随机种子；非负整数透传为 `metadata.seed` |

Kling 视频节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | Kling 文生视频、图生视频/首尾帧或 O3 参考生视频模型 |
| `prompt` | 文生视频和参考生视频必填；图生视频可选 |
| `seconds` | 5 或 10 秒 |
| `ratio` | 画幅比例，非 `adaptive` 时透传为 `metadata.ratio` |
| `negative_prompt` | 可选反向提示词，透传为 `metadata.negative_prompt` |
| `image1` | 图生视频首帧；参考生视频图1 |
| `image2` | 图生视频可选尾帧；参考生视频图2 |
| `image3` ... `image4` | O3 参考生视频可选参考图 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

Kling O3 视频编辑节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | `kling-o3-std-edit` 或 `kling-o3-pro-edit` |
| `video_url` | 可选公网 MP4 直链；连接 `input_video` 时可留空 |
| `input_video` | 可选 ComfyUI `VIDEO` 输入；节点会上传后写入 `metadata.content[0].video_url` |
| `prompt` | 必填编辑提示词 |
| `seconds` | 5 或 10 秒 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

Hailuo 2.3 节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | Hailuo 2.3 文生视频、图生视频或 fast 图生视频模型 |
| `prompt` | 文生视频必填；图生视频可选，最多 2000 字符 |
| `seconds` | 6 或 10 秒 |
| `resolution` | `768p` 或 `1080p`；`1080p` 仅支持 6 秒 |
| `ratio` | 仅文生视频使用，非 `adaptive` 时透传为 `metadata.ratio` |
| `first_image` | 图生视频 / fast 图生视频必填首帧图，作为 `images[0]` 提交 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

Seedance 2.5 Standard 节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | 六个 Seedance 2.5 Standard 国内/海外 T2V、I2V、Multi 模型 |
| `prompt` | T2V 与 Multi 必填；I2V 可选，最多 20480 字符 |
| `seconds` | 4 到 30 秒；`-1` 由模型智能选择时长 |
| `resolution` | `480p`、`720p`、`1080p`、`2k`、`4k` |
| `ratio` | `adaptive`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16`、`21:9` |
| `image1` / `image2` | I2V 的必填首帧和可选尾帧；Multi 的参考图片 1、2 |
| `image3` ... `image9` | Multi 可选参考图片 |
| `video1` ... `video3` | Multi 可选参考视频 |
| `audio1` ... `audio3` | Multi 可选参考音频 |
| `generate_audio` | 是否生成配音或音效 |
| `seed` | `-1` 为随机；非负整数作为固定 seed 提交 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API Key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

Hailuo H3 节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | Hailuo H3 国内/海外 T2V、I2V 或 Multi 六个模型 |
| `prompt` | T2V 与 Multi 必填；I2V 可选，最多 20480 字符 |
| `seconds` | 5 到 15 秒 |
| `resolution` | `768P` 或 `2K` |
| `ratio` | T2V 与 Multi 使用，支持 `adaptive`；I2V 不提交 |
| `image1` / `image2` | I2V 的必填首帧和可选尾帧；Multi 的参考图 1、2 |
| `image3` ... `image9` | Multi 可选参考图 |
| `video1` ... `video3` | Multi 可选参考视频 |
| `audio1` ... `audio3` | Multi 可选参考音频 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

FLUX 3 Video 节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | FLUX 3 国内/海外 T2V、I2V、V2V 或 Draft Enhance 八个模型 |
| `prompt` | T2V、I2V、V2V 必填；Draft Enhance 不使用 |
| `seconds` | 5 到 20 秒 |
| `resolution` | `hd` 或 `fhd` |
| `ratio` | `auto`、`21:9`、`2:1`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16` |
| `draft` | 普通生成开启后请求可复用草稿缓存 |
| `audio_mode` | 使用接口默认值、开启或关闭生成音频 |
| `safety_tolerance` | 使用接口默认值，或发送 0 到 4 |
| `image1` ... `image10` | I2V 关键帧，`image1` 必填，按插槽顺序提交 |
| `input_video` / `video_url` | V2V 本地视频或公网 MP4 直链 |
| `draft_cache` | Draft Enhance 必填，可直接连接前一个草稿节点的同名输出 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

MiniMax H3 OW Fast 节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | `minimax-h3-ow-i2v-fast` 或 `minimax-h3-ow-r2v-fast` |
| `prompt` | R2V Fast 必填；I2V Fast 可选，最多 20480 字符 |
| `seconds` | `5`、`10` 或 `15` 秒 |
| `resolution` | `480p` 或 `720p` |
| `ratio` | `1:1`、`2:3`、`3:2`、`3:4`、`4:3`、`9:16`、`16:9`、`21:9` |
| `image1` | 两个模型均必填；I2V Fast 只允许这一张图 |
| `image2` ... `image9` | 仅 R2V Fast 使用的可选参考图 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

Vidu Q3 视频节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | Vidu Q3 文生、图生、首尾帧或参考生视频模型 |
| `prompt` | 文生视频必填；其他模式可按模型需要填写 |
| `seconds` | 4 到 15 秒，按字符串提交 |
| `ratio` | 画幅比例，非 `adaptive` 时透传为 `metadata.ratio` |
| `resolution` | `default`、`720p` 或 `1080p`；`default` 不提交该字段 |
| `seed` | `-1` 为随机种子；非负整数透传为 `metadata.seed` |
| `image1` | 图生视频首帧；首尾帧起始帧；参考生视频图1 |
| `image2` | 首尾帧结束帧；参考生视频图2 |
| `image3` ... `image9` | 参考生视频可选参考图 |

Vidu Q3 短剧节点参数：

| 参数 | 说明 |
| --- | --- |
| `model` | `vidu-q3-drama-short-play` 或 `vidu-q3-ad-short-play` |
| `prompt` | 短剧 / 广告短片脚本内容 |
| `script_name` | 透传为 `metadata.script_name` |
| `resolution` | 固定为 `1080p` |
| `duration` | 8 到 12 秒 |
| `aspect_ratio` | `9:16` 或 `16:9` |
| `style` | 视频风格，最多 30 字符 |
| `asset_type` | 所有参考资产使用的类型：`character`、`scene` 或 `prop` |
| `asset_name_prefix` | 参考资产名称前缀，节点会生成 `前缀 1`、`前缀 2` |
| `asset_description` | 所有参考资产使用的描述 |
| `asset_image1` ... `asset_image14` | 参考资产图，至少连接 1 张；节点上传后写入 `metadata.assets[].image_uri` |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

Zhenzhen Upscaler 节点参数：

| 参数 | 说明 |
| --- | --- |
| `video_url` | 可选公网 MP4 直链；连接 `input_video` 时可留空 |
| `resolution` | 目标分辨率：`720p`、`1080p`、`2k` 或 `4k` |
| `input_video` | 可选 ComfyUI `VIDEO` 输入；节点会上传后作为 `metadata.content[0].video_url` 提交 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回占位视频，而不是中断整个工作流 |

Doubao Seed Audio 参数：

| 参数 | 说明 |
| --- | --- |
| `prompt` | 必填，5 到 2048 字符 |
| `speaker` | 可选音色 ID；与参考图、参考音频互斥 |
| `output_format` | `wav`、`mp3`、`pcm`、`ogg_opus`，默认 `wav` |
| `sample_rate` | `8000`、`16000`、`24000`、`32000`、`44100` |
| `speech_rate` | 语速，`-50` 到 `100` |
| `loudness_rate` | 音量，`-50` 到 `100` |
| `pitch_rate` | 音高，`-12` 到 `12` |
| `reference_image` | 可选参考图，取首张；与 `speaker` / 参考音频互斥 |
| `reference_audio1` ... `reference_audio3` | 可选参考音频，最多 3 段；与 `speaker` / 参考图互斥 |

Whisper 1 语音转写参数：

| 参数 | 说明 |
| --- | --- |
| `audio` | 必填，ComfyUI `AUDIO` 输入 |
| `model` | 固定为 `whisper-1` |
| `response_format` | `json`、`verbose_json`、`srt`、`text` 或 `vtt`，默认 `json` |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |
| `skip_error` | 开启后失败时返回空转写和错误 JSON，而不是中断整个工作流 |

Suno 音乐节点参数：

| 参数 | 说明 |
| --- | --- |
| `operation` | 31 项官方操作；选择后动态显示相关控件 |
| `prompt` | 音乐生成、歌词、音效、翻唱、双曲混合、采样和三项添加动作使用；支持前置字符串节点 |
| `version` | 仅当前操作支持版本时发送 |
| `custom` / `instrumental` / `title` / `style` / `vocal_gender` | 音乐生成专用设置 |
| `task_id` / `task_id_2` / `audio_index` | 引用前置 Suno 任务；`audio_index` 从 1 开始 |
| `audio1` ... `audio4` | 本地音频；用于素材导入、创建音色或参考生成 |
| `audio_url1` ... `audio_url4` | 公网音频 URL，不能与同槽本地音频同时使用 |
| `continue_at` / `start_s` / `end_s` / `duration_s` / `speed` | 续写与编辑操作的时间或速度参数 |
| `api_config` / `skip_error` | 可选配置节点与批处理错误策略 |

Midjourney 节点参数：

| 参数 | 说明 |
| --- | --- |
| `operation` | 16 项官方操作；action ID 后附中文用途，选择后动态显示相关控件 |
| `prompt` | Imagine / Edits 必填；Modal、Video 和 Remix 按当前操作选填；支持前置字符串节点 |
| `image1` ... `image4` | 本地图片输入；同槽不能再填写 `image_url1` ... `image_url4` |
| `task_id` / `custom_id` | 连接父任务，或使用服务端按钮提供的 custom ID |
| `index` | 图片二次操作使用 1 到 4；任务复用视频使用 0 到 3；`-1` 表示不发送 |
| `speed` / `dimensions` / `version` | 默认 `relax` / `SQUARE` / `8.2`；当前操作支持时才会发送 |
| `size` / `custom_size` | 常用比例下拉，默认 `1:1`；选择 `custom` 后可手填正整数 `w:h` 比例 |
| `seed` / `quality` / `stylize` / `chaos` / `weird` | Imagine / Edits 的结构化生成参数 |
| `direction` / `zoom_ratio` | Pan 方向和 Zoom 比例 |
| `modal_mode` / `mask` / `mask_url` | Modal 的局部重绘或外扩设置；本地 MASK 会自动转换并上传 |
| `video_type` / `animate_mode` / `motion` / `batch_size` | 图生视频类型、衍生模式、运动幅度和结果数量 |
| `end_image` / `end_url` | 可选结束帧；设置后自动使用首尾帧视频类型 |
| `metadata_json` | 可选 JSON 对象，仅当前操作支持时发送 |
| `api_config` / `skip_error` | 可选配置节点与批处理错误策略 |

## 多模态提示词

Seedance 2.0 与 Hailuo 等多模态节点支持：

- 最多 9 张图片
- 最多 3 个视频
- 最多 3 段音频

Seedance 2.5 Multi 支持：

- 最多 30 张图片
- 最多 10 个视频
- 最多 10 段音频
- 所有类型合计最多 50 个参考素材
- 单段参考视频或音频为 2 到 30 秒，参考音视频总时长不超过 30 秒

至少需要连接 1 个参考素材。

在提示词中使用下面的写法引用素材：

- `@Image 1`
- `@Video 1`
- `@Audio 1`

素材编号按连接的输入槽位顺序生成。如果连接了 `image1` 和 `image3`，但跳过 `image2`，插件会自动压缩编号为 `@Image 1`、`@Image 2`，并在控制台输出提示。

参考视频建议使用 MP4，单个文件不超过 50 MB。音频参考也建议控制在 50 MB 以内。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SEEDANCE_API_KEY` | 空 | 未连接配置节点时使用的 API 令牌 |
| `SEEDANCE_BASE_URL` | `https://api.seedance.nz` | API 网关地址 |
| `SEEDANCE_POLL_INTERVAL` | `4` | 轮询间隔，单位秒 |
| `SEEDANCE_MAX_POLL_TIME` | `1800` | 最大轮询时间，单位秒 |
| `SEEDANCE_TIMEOUT` | `60` | 提交任务请求超时，单位秒 |
| `SEEDANCE_UPLOAD_TIMEOUT` | `180` | 上传素材请求超时，单位秒 |
| `SEEDANCE_CA_BUNDLE` | 空 | 可选，自定义 CA 证书包路径，用于证书链排障 |
| `SEEDANCE_FFMPEG` | 自动查找 | 可选，指定 FFmpeg 可执行文件；未设置时检查 PATH 和整合包内置路径 |
| `SEEDANCE_CURL` | 自动查找 | 可选，指定系统 `curl` 可执行文件；生成媒体直连失败时自动启用独立下载通道 |
| `SEEDANCE_SSL_VERIFY` | `1` | 设为 `0` 可关闭 SSL 校验，仅建议临时排障使用 |
| `SEEDANCE_IMAGE_CONCURRENCY` | `30` | 图片并发工作线程数，可设置 1 到 30；不会改变接收节点的 30 个插槽 |
| `SEEDANCE_VIDEO_CONCURRENCY` | `10` | 视频并发工作线程数，可设置 1 到 10；不会改变接收节点的 10 个插槽 |

## 稳定性策略

- 提交任务时，网络错误、HTTP 429、HTTP 5xx 会自动重试。
- 参数错误、鉴权失败等业务错误会立即失败，不会重复提交生成请求。
- 轮询任务时，会容忍短暂网络错误、非 200 响应和 JSON 解析失败。
- 上传素材遇到 API 限流时，会等待后继续重试。
- 视频结果使用 8 秒连接、60 秒读取和单次 180 秒总时限；首次网络或完整性错误会立即切换系统下载通道，失败后再通过全新 Python Session 短间隔重试。
- 图片任务使用独立状态规则轮询：`SUCCESS` 成功、`FAILURE` 失败，并自动下载临时结果直链。
- 下载图片使用流式读取、8 秒连接超时、60 秒读取超时和单次 60 秒总时限。首次网络错误会立即重建线程连接并切换系统下载通道；若仍失败，再以 1 秒、2 秒短间隔使用全新 Python Session 重试，成功后返回标准 ComfyUI `IMAGE` 张量。
- 音频任务使用 `/v1/audio/generations` 独立状态规则轮询；结果下载使用 60 秒读取超时、300 秒总时限、原子落盘与双通道恢复，成功解码后才返回 ComfyUI `AUDIO`。
- Whisper 转写使用同步 `/v1/audio/transcriptions` multipart 请求，不进行任务轮询。
- Suno 任务查询兼容运行阶段的 `data[]` 和完成阶段的 `data` 对象响应。
- Suno 会分类并转存识别出的音频、视频和通用文件结果，同时保留全部 URL 和本地路径。
- Suno 多产物动作若个别直链失效，会保留原 URL 顺序、用空路径占位并在响应中加入脱敏警告；只有全部产物都无法下载时才中止。
- Midjourney 提交使用显式 action 路径；任务查询会在文档登记的三条路径间兼容回退，并在首次成功后固定查询路径。
- Midjourney 的 `MODAL` 是等待补充参数的合法中间状态；Inpaint 节点会在该状态正常返回任务 ID。
- Midjourney 图像和视频结果支持多产物下载；单个产物失败时保留 URL 与空路径，全部下载失败时才中止。
- Midjourney 结果只从 `data` / `result` / `task` / `output` 任务信封提取，不会把回显请求或自定义 metadata 中的素材 URL 误认成生成结果。
- 每个执行线程使用独立 HTTP Session，同一线程内复用连接，多任务并发时不会共享可变 Session 状态。
- 图片与视频使用独立的延迟线程池；并发子任务不直接争用 ComfyUI 进度条，接收节点统一汇总各任务的上传、轮询和下载进度。
- 并发接收器按 Future 完成通知收集结果，再恢复输入槽位顺序；用户中断时会通知本地轮询停止并取消尚未开始的任务。
- `raw`、`draft`、`hd`、`stop` 与 Niji 的版本组合按官方约束在提交前校验。
- Video 与两种 Remix 不发送文档未登记的 metadata；`CANCEL` 会作为失败终态立即结束查询；Midjourney 的 `skip_error` 同时提供图片和视频占位。
- Seed Audio 已实测可在没有 `torchaudio` 时通过 SciPy 回退解码 24 kHz 双声道 WAV。
- 音乐音频优先使用 `torchaudio` 解码；不可用时自动使用 `SEEDANCE_FFMPEG`、PATH 或整合包内的 FFmpeg。
- 视频节点 `skip_error=True` 时会生成一个错误占位视频；音频节点会返回 1 秒静音，方便批量流程继续往下跑。

## 常见问题

### 节点没有出现

确认插件路径是：

```text
ComfyUI/custom_nodes/ComfyUI_Seedance
```

安装依赖后需要重启 ComfyUI。

### 提示缺少 API key

请连接 `Seedance API Config`，或设置 `SEEDANCE_API_KEY`，或创建 `config/.env`。

### SSL 证书错误

插件不依赖 `truststore`。默认使用 `requests` 的证书校验链路；Windows 上会额外读取系统 ROOT/CA 证书库，以适配 ComfyUI 便携 Python 的证书环境。

如果仍遇到证书错误，先尝试在 ComfyUI 使用的 Python 环境中更新基础网络依赖：

```bash
python -m pip install -U requests certifi
```

也可以设置 `SEEDANCE_CA_BUNDLE` 指向自定义 CA 证书包。仍然无法连接时，可以临时设置 `SEEDANCE_SSL_VERIFY=0` 跳过 SSL 校验。

### `native1080p` 或 `native4k` 被拒绝

请切换到 Standard 档模型，或改用 `480p`、`720p`、`1080p`、`2k`、`4k`。

### 多模态上传很慢

API 可能对单个令牌的上传频率限流。插件会自动等待和重试，大素材或多素材工作流开始生成前会更慢一些。

### Seed Audio WAV 显示的时长异常

上游可能返回使用 `0xFFFFFFFF` 流式长度标记的 WAV。部分严格按 RIFF 头读取的软件会显示错误时长或给出长度警告，但插件会按实际数据解码并返回正确的 ComfyUI `AUDIO`。如需在外部软件使用，可先通过 ComfyUI 音频保存节点重新保存。

## 注意事项

- 本插件会把提示词和连接的参考素材发送到配置的 Seedance API endpoint。
- 结果直链可能有有效期，重要结果请及时保存。
- 不要把 API key 写进公开工作流或提交到仓库。
