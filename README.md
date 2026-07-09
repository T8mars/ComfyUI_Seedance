# ComfyUI_Seedance

Seedance 2.0 视频生成 API（[api.seedance.nz](https://api.seedance.nz)，基于开源网关 [new-api](https://github.com/QuantumNous/new-api) 搭建）的 ComfyUI 节点插件。

平台共提供 18 个模型（国内/海外 × standard/fast/mini × 文生/图生/多模态视频）。本插件按**任务类型**合并为 3 个生成节点，在节点内通过 `model` 下拉框选择档位与地区，另有 1 个 API 配置节点：

| 节点 | 用途 | 对应模型 |
| --- | --- | --- |
| `Seedance API Config` | 提供 base_url + api_key | - |
| `Seedance 文生视频 (Text to Video)` | 纯文本生成视频 | 6 个 `-t2v` 模型 |
| `Seedance 图生视频 (Image to Video)` | 首帧图（+可选尾帧图）生成视频 | 6 个 `-i2v` 模型 |
| `Seedance 多模态视频 (Multimodal Video)` | 图片×9 + 视频×3 + 音频×3 混合参考 | 6 个 `-multi` 模型 |

所有参考素材（IMAGE/VIDEO/AUDIO）会自动通过平台的 `/v1/files/upload` 接口上传换取 URL，无需自备图床。

## 安装

```bash
cd ComfyUI/custom_nodes
git clone <this repo> ComfyUI_Seedance
# 依赖仅 requests（ComfyUI 自带）+ truststore（推荐）：
path/to/python -m pip install -r ComfyUI_Seedance/requirements.txt
```

重启 ComfyUI 即可在 `Seedance` 分类下看到节点。

## 快速上手

1. 登录 [api.seedance.nz/console](https://api.seedance.nz/console) → 「API 令牌」→ 新建令牌
2. 添加 `Seedance API Config` 节点，填入 api_key
3. 添加任一生成节点，连上 `api_config`，填写提示词后运行
4. `examples/` 目录内有 3 个任务类型的示例工作流，可直接拖入 ComfyUI

API key 也可以不写进工作流，改用环境变量 `SEEDANCE_API_KEY`（或插件目录下 `config/.env` 文件），此时无需连接配置节点。

## 节点参数说明

| 参数 | 说明 |
| --- | --- |
| `model` | `standard`（标准）/ `fast`（快速）/ `mini`（轻量，最便宜）三档；带 `global-` 为海外版通道，价格与国内版相同 |
| `prompt` | 提示词（≤20480 字符）。多模态节点中用 `@Image 1`、`@Video 1`、`@Audio 1` 指代第几个素材 |
| `seconds` | 视频时长 4~15 秒，`-1` 表示模型智能选择 |
| `resolution` | `1080p/2k/4k` 为 720p 超分档（按输出秒数加收附加费）；`native1080p/native4k` 仅 Standard 档模型支持（提交前会校验） |
| `ratio` | 画面比例，`adaptive` 为自适应输入素材 |
| `generate_audio` | 是否生成配音/音效，默认开 |
| `seed` | `-1` 为随机；≥0 时透传给模型 |
| `skip_error` | 开启后失败时输出占位错误视频而不中断工作流，适合批量跑图 |

输出：`video`（VIDEO，已下载到 output 目录）、`video_url`（结果直链，带签名有效期，请及时转存）、`task_id`、`response`（完整 JSON 响应）。

### 多模态节点注意事项

- 图片最多 9 张、视频最多 3 个（MP4 ≤50MB）、音频最多 3 个（≤50MB），**至少连接 1 个素材**
- 素材编号与输入槽位对应：`image1` → `@Image 1`。跳槽位连接（如只连 image1、image3）会被自动压缩编号并在控制台提示
- 传入参考视频后按"有参考视频"低单价档计费

## 可靠性设计

- **提交**：网络错误 / 5xx / 429 自动重试（最多 3 次指数退避）；参数错误、鉴权失败等业务错误立即报错不重试
- **轮询**：连续失败计数（网络抖动、非 200、JSON 解析失败均容忍 6 次），任务业务失败立即终止；进度条实时对接 API 的 `progress` 字段
- **上传**：命中平台限流（每令牌 10 次/分钟）时自动等待 30 秒重试，大批量素材也能跑完
- **下载**：结果视频下载失败自动重试 3 次
- **计费安全**：提交失败 / 生成失败平台全额退款，节点端失败不会白扣费

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SEEDANCE_API_KEY` | - | API 令牌（未连接配置节点时使用） |
| `SEEDANCE_BASE_URL` | `https://api.seedance.nz` | 网关地址 |
| `SEEDANCE_POLL_INTERVAL` | `4` | 轮询间隔（秒） |
| `SEEDANCE_MAX_POLL_TIME` | `1800` | 轮询超时（秒） |
| `SEEDANCE_TIMEOUT` | `60` | 提交请求超时（秒） |
| `SEEDANCE_UPLOAD_TIMEOUT` | `180` | 素材上传超时（秒） |
| `SEEDANCE_SSL_VERIFY` | `1` | 设为 `0` 可跳过 SSL 证书校验（不推荐，优先安装 `truststore`） |

> 便携版 ComfyUI 自带的 certifi CA 证书可能过旧导致 SSL 校验失败。插件在检测到 `truststore` 包时会自动改用操作系统信任库（与浏览器行为一致），`requirements.txt` 已包含该依赖。

## 计费说明

按模型实际消耗 token 计费（超分档另收每秒附加费），任务成功后按量结算、多退少补；提交前只能估算区间。建议先用 `mini` 档 + `480p` + 短时长试跑，从控制台确认单次成本后再上高配档位。
