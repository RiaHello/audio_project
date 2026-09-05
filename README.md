# 语音约碰面地点

按住说话，找出同一座城市里两个人之间的碰面地点。当前版本包含健康检查、本地录音、上传、语音识别、地址提取、中点搜店、推荐语和语音。前端尚未调用业务接口。

## 环境

- Python 3.11
- Node.js 22.12 及以上的 22.x
- 后端端口 `8003`，前端端口 `5175`
- 本机需安装 FFmpeg（提供 `ffprobe`）。后端用它探测真实容器、编码和时长，不转码。Chrome 的 WebM 常缺少 Duration 元数据，`ffprobe` 可从音频流或 packet 时间戳读取时长。

macOS 安装（请自行执行，不要跳过）：

```bash
brew install ffmpeg
ffprobe -version
```

## 配置

```bash
cp backend/.env.example backend/.env
```

外部服务密钥可先留空。健康检查不调用百炼、DeepSeek 或高德。

## 启动后端

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8003
```

若本机开启了 SOCKS 代理（Clash / V2Ray 等），需要 `httpx[socks]`。依赖清单已包含该项；若启动过旧环境，请重新执行上面的 `pip install -r requirements.txt` 后再启动。
```

接口文档：<http://localhost:8003/docs>  
健康检查：<http://localhost:8003/health>

## 启动前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

页面：<http://localhost:5175>

## 如何验证录音

前端需已启动。建议使用支持 WebM/Opus 的 Chrome 或 Edge。本轮不调用上传或其他业务接口。

1. 打开 <http://localhost:5175>，确认城市默认为「杭州」，可修改。
2. 按住「按住说话」，允许麦克风；按钮应变为「松开结束」，并显示秒数。
3. 松开后出现试听播放器和「下载录音文件」。页面会显示 MIME 类型、大小和时长。
4. 点一下松开（不足 1 秒）应提示时长不合规，不生成可下载文件。
5. 录音中按 Esc 或点「取消录音」，应回到未完成状态并释放麦克风（浏览器麦克风图标消失）。
6. 按住后把指针移出按钮再松开，也应结束录音并释放麦克风。
7. 按住直到 60 秒，应自动结束并保留录音。

下载后检查格式、大小和时长（将路径换成你的下载文件）：

```bash
ls -lh ~/Downloads/meetup-recording-*.webm

ffprobe -v error -show_entries format=format_name,filename,size,duration \
  -show_entries stream=codec_name,codec_type,codec_mime \
  -of default=nw=1 \
  ~/Downloads/meetup-recording-*.webm
```

Chrome 的 WebM 常常没有容器级 Duration。若 `duration=N/A`，不要当成文件损坏，可改用数据包时间戳：

```bash
ffprobe -v error -select_streams a:0 \
  -show_entries packet=pts_time \
  -of csv=p=0 \
  ~/Downloads/meetup-recording-*.webm | tail -n 1
```

预期：容器为 `webm`/`matroska`，音频编码为 `opus`，大小不超过 5MB，时长大约在 1–60 秒（与页面显示接近）。

## 如何验证 POST /upload

后端改代码后需重启 `uvicorn`。先确认 `ffprobe` 可用。本轮未接前端，请用 `/docs` 或 curl。

1. 打开 <http://localhost:8003/docs>
2. 找到 `POST /upload`，点 Try it out
3. 在 `file` 选择上一轮下载的 `meetup-recording-*.webm`
4. Execute

或：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/upload \
  -F "file=@$HOME/Downloads/meetup-recording-XXXX.webm;type=audio/webm"
```

把文件名换成你的下载文件。

### 正常上传

- 状态码：`200`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "data": {
    "audio_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

`audio_id` 是 UUID，不是路径。录音保存在 `backend/storage/audio/<audio_id>/recording.webm`，同目录 `meta.json` 含 `created_at`（UTC），供之后 24 小时过期校验使用。

### 格式不支持

上传任意非 WebM/Opus 文件，例如一个 `.txt` 或 `.mp3`：

```bash
echo 'not audio' > /tmp/not-audio.txt
curl -sS -D - -X POST http://127.0.0.1:8003/upload \
  -F "file=@/tmp/not-audio.txt;type=text/plain"
```

- 状态码：`415`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "error": {
    "code": "UNSUPPORTED_MEDIA_TYPE",
    "message": "仅支持 WebM/Opus 录音，请更换浏览器后重试。",
    "stage": "upload"
  }
}
```

### 文件过大

大小校验在格式探测之前，可用大于 5MB 的任意文件：

```bash
dd if=/dev/zero of=/tmp/huge.webm bs=1048576 count=6
curl -sS -D - -X POST http://127.0.0.1:8003/upload \
  -F "file=@/tmp/huge.webm;type=audio/webm"
```

- 状态码：`413`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "error": {
    "code": "FILE_TOO_LARGE",
    "message": "录音文件超过 5MB，请缩短录音后重试。",
    "stage": "upload"
  }
}
```

### 时长不合规

需要真实的 WebM/Opus，否则会先变成 415。若已安装 ffmpeg：

```bash
ffmpeg -y -f lavfi -i anullsrc=r=48000:cl=mono -t 0.5 -c:a libopus /tmp/short.webm
curl -sS -D - -X POST http://127.0.0.1:8003/upload \
  -F "file=@/tmp/short.webm;type=audio/webm"
```

- 状态码：`422`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "error": {
    "code": "AUDIO_DURATION_INVALID",
    "message": "录音时长需在 1 到 60 秒之间，请重新录制。",
    "stage": "upload"
  }
}
```

超过 60 秒把上面的 `-t 0.5` 改成 `-t 61`，状态码和 `code` 相同。

缺少 `file` 字段时状态码 `422`，`code` 为 `VALIDATION_ERROR`。

可选 Mock 测试（不调用真实 ffprobe，不能代替真实录音上传）：

```bash
cd backend
source .venv/bin/activate
pytest tests/test_upload.py
```

## 如何验证 POST /asr

后端改代码后需重启 `uvicorn`。本轮未接前端。

### Mock（无费用）

不调用百炼，不能证明真实识别已跑通：

```bash
cd backend
source .venv/bin/activate
pytest tests/test_asr.py
```

覆盖：识别成功、编号不存在、已过期、识别为空、超时 504、上游失败 502、缺字段 422。

本地也可不填密钥、用一个不存在的 `audio_id` 测 404，这不会产生调用费用：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/asr \
  -H "Content-Type: application/json" \
  -d '{"audio_id":"00000000-0000-0000-0000-000000000000"}'
```

- 状态码：`404`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "error": {
    "code": "AUDIO_NOT_FOUND",
    "message": "录音不存在或已过期，请重新录音。",
    "stage": "asr"
  }
}
```

缺字段：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/asr \
  -H "Content-Type: application/json" \
  -d '{}'
```

- 状态码：`422`，`code` 为 `VALIDATION_ERROR`

### 真实识别（需要 BAILIAN_API_KEY，会产生调用费用）

请你确认后再执行。密钥填在 `backend/.env` 的 `BAILIAN_API_KEY`，使用北京地域；`BAILIAN_ASR_URL` 与 `BAILIAN_ASR_MODEL` 保持默认。

1. 先上传录音，记下返回的 `audio_id`：

```bash
curl -sS -X POST http://127.0.0.1:8003/upload \
  -F "file=@$HOME/Downloads/meetup-recording-XXXX.webm;type=audio/webm"
```

或在 <http://localhost:8003/docs> 执行 `POST /upload`。

2. 把该 `audio_id` 填入 `POST /asr`（/docs 里 Try it out，或 curl）：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/asr \
  -H "Content-Type: application/json" \
  -d '{"audio_id":"粘贴上传返回的audio_id"}'
```

正常时应为 `200`，`data.text` 是这段录音的真实识别结果，而不是固定文案：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "data": {
    "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。"
  }
}
```

上面的 `text` 仅为结构示例；你应看到自己说的话。

若识别结果为空：`422` / `ASR_EMPTY`。  
若百炼超时：`504` / `UPSTREAM_TIMEOUT`。  
若百炼 HTTP 或业务失败：`502` / `UPSTREAM_ERROR`。  
若返回结构无法解析：`502` / `MODEL_OUTPUT_INVALID`。

## 如何验证 POST /extract

后端改代码后需重启 `uvicorn`。本轮未接前端。提示词在 `backend/prompts/extract.txt`。

模型内部 JSON 含 `party_count`、`incomplete_reason` 等诊断字段；接口成功时只返回五个业务字段，不会把诊断字段传给调用方。模型 JSON 非法、缺字段或类型错误返回 `502` / `MODEL_OUTPUT_INVALID`，不要理解成用户没说清楚。

### Mock（无费用）

```bash
cd backend
source .venv/bin/activate
pytest tests/test_extract.py
```

不能证明真实 DeepSeek 已跑通。

### 真实调用（需要 DEEPSEEK_API_KEY，会产生费用）

请你确认后再执行。在 <http://localhost:8003/docs> 打开 `POST /extract`，Try it out，粘贴下面请求体。

**1. 正常提取**

```json
{
  "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。",
  "city": "杭州"
}
```

模型原始输出（内部，不会原样返回）类似：

```json
{
  "city_a": "杭州",
  "address_a": "杭州东站",
  "city_b": "杭州",
  "address_b": "西湖龙翔桥地铁站",
  "category": "咖啡店",
  "party_count": 2,
  "incomplete_reason": null
}
```

接口最终返回 `200`：

```json
{
  "request_id": "……",
  "data": {
    "city_a": "杭州",
    "address_a": "杭州东站",
    "city_b": "杭州",
    "address_b": "西湖龙翔桥地铁站",
    "category": "咖啡店"
  }
}
```

**2. 口述未提城市，使用页面城市**

```json
{
  "text": "我在东站，朋友在龙翔桥地铁站，找个咖啡店。",
  "city": "杭州"
}
```

预期仍为杭州两地；`data` 五个字段，不出现 `party_count`。

**3. 类别归一化（喝咖啡 → 咖啡店）**

```json
{
  "text": "我在杭州东站，朋友在龙翔桥地铁站，找个地方喝咖啡。",
  "city": "杭州"
}
```

预期 `category` 为 `咖啡店`。

**4. 地址缺失 → 422 EXTRACT_INCOMPLETE**

```json
{
  "text": "我在杭州东站，朋友也过来，帮我们找个咖啡店。",
  "city": "杭州"
}
```

模型可能输出 `address_b: null`、`incomplete_reason: "missing_address"`。接口返回：

```json
{
  "request_id": "……",
  "error": {
    "code": "EXTRACT_INCOMPLETE",
    "message": "没听清两个人的具体地点，请再说一次各自所在的站名或地址。",
    "stage": "extract"
  }
}
```

**5. 「我家」含糊表达 → 422 EXTRACT_INCOMPLETE**

```json
{
  "text": "我在我家，朋友在杭州东站，找个咖啡店。",
  "city": "杭州"
}
```

**6. 人数不符 → 422 PARTY_COUNT_INVALID**

```json
{
  "text": "我、小李和小王，我在杭州东站，他们在龙翔桥地铁站，找咖啡店。",
  "city": "杭州"
}
```

**7. 跨城 → 422 CROSS_CITY**

```json
{
  "text": "我在杭州东站，朋友在上海虹桥火车站，找个咖啡店。",
  "city": "杭州"
}
```

缺 `text` 或 `city`：`422` / `VALIDATION_ERROR`。  
DeepSeek 超时：`504` / `UPSTREAM_TIMEOUT`。  
上游失败：`502` / `UPSTREAM_ERROR`。

## 如何验证 POST /search

后端改代码后需重启 `uvicorn`。本轮未接前端。`/search` 总预算 20 秒：双方地理编码各 4 秒，2000 米周边 4 秒，必要时 5000 米再 4 秒。

高德 `location` 是 **经度在前、纬度在后** 的 `lng,lat`。中点是两地经度、纬度分别算术平均，保留 6 位小数，坐标系保持高德 GCJ-02，不转 WGS84。`distance_to_midpoint_m` 只表示店铺到这个地理中点的距离（优先用高德返回的有效数值，缺失则用 Haversine，地球半径 6371000 米），**不是**双方出行时间，也不能理解成「两个人路上一样久」。

定位校验会看城市、匹配级别、地点名称和地址。多个候选必须全部两两比较；只有核心地名相同且最大间距 ≤ 150 米才合并。相距约 300 米的不同候选不会自动当成同一地点。无法可靠区分时返回 `GEO_AMBIGUOUS`。

成功时把结果写到 `backend/storage/search/<search_id>/result.json`，含 `created_at`（UTC），供后续 `/finalize` 使用。`search_id` 是 UUID，不是文件路径。

### Mock（无费用，不调用高德）

不能证明真实高德已跑通：

```bash
cd backend
source .venv/bin/activate
pytest tests/test_search.py
```

覆盖：正常搜店并按距离排序、最多 3 家、缺失距离不填 0、2000 米为空时扩大到 5000 米、定位不明确、无法定位、无候选、超时 504、上游失败 502、缺字段 422。同时核对经度在前、中点为算术平均。

### 真实调用（需要 AMAP_API_KEY，会产生调用次数）

请你确认后再执行。密钥填在 `backend/.env` 的 `AMAP_API_KEY`，使用 Web 服务类型 Key。在 <http://localhost:8003/docs> 打开 `POST /search`，Try it out，或用 curl。

**1. 正常搜店**

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/search \
  -H "Content-Type: application/json" \
  -d '{
    "city_a": "杭州",
    "address_a": "杭州东站",
    "city_b": "杭州",
    "address_b": "西湖龙翔桥地铁站",
    "category": "咖啡店"
  }'
```

预期 `200`，结构示例（坐标和店名以高德实时结果为准）：

```json
{
  "request_id": "……",
  "data": {
    "search_id": "s9f8e7d6-c5b4-3210-aaaa-bbbbccccdddd",
    "midpoint": {
      "longitude": 120.210123,
      "latitude": 30.274456
    },
    "pois": [
      {
        "name": "某咖啡店湖滨店",
        "address": "杭州市上城区湖滨路1号",
        "distance_to_midpoint_m": 320
      }
    ]
  }
}
```

核对方法：

1. `search_id` 为 UUID；`backend/storage/search/<search_id>/result.json` 存在且含 `created_at`、`midpoint`、`pois`。
2. 打开该文件中的 `point_a.longitude` / `point_a.latitude` 与 `point_b`，确认与高德 `location` 一致：**第一个数是经度，第二个是纬度**。杭州大约是经度 `120`、纬度 `30`，如果看到 `30.x, 120.x` 则顺序反了。
3. 中点应为 `((lng_a + lng_b) / 2, (lat_a + lat_b) / 2)`，与 `data.midpoint` 一致（6 位小数）。
4. `pois` 最多 3 家，`distance_to_midpoint_m` 升序；这是到中点的米数，不要据此说两人出行时间相同。
5. 若 2000 米没有有效店，后端会再查 5000 米；`result.json` 里的 `radius_m` 为实际采用的半径。

**2. 定位不明确 → 422 GEO_AMBIGUOUS**

用容易对应多个地点的名称，例如只说「西湖」：

```json
{
  "city_a": "杭州",
  "address_a": "西湖",
  "city_b": "杭州",
  "address_b": "杭州东站",
  "category": "咖啡店"
}
```

若高德返回多个无法按 150 米 + 同一核心地名合并的候选，接口返回：

```json
{
  "request_id": "……",
  "error": {
    "code": "GEO_AMBIGUOUS",
    "message": "找到多个可能的地点，请补充更具体的站名、出入口或地址。",
    "stage": "search"
  }
}
```

真实高德若碰巧只命中一个可接受结果，会返回 200；**「300 米内不当成同一地点」以 Mock 用例为准**。

**3. 无法定位 → 422 GEO_UNRESOLVED**

```json
{
  "city_a": "杭州",
  "address_a": "不存在的某某路99999号",
  "city_b": "杭州",
  "address_b": "杭州东站",
  "category": "咖啡店"
}
```

```json
{
  "request_id": "……",
  "error": {
    "code": "GEO_UNRESOLVED",
    "message": "地点无法定位，请说更具体的站名或地址。",
    "stage": "search"
  }
}
```

**4. 无候选 → 422 NO_POI**

真实高德对 `keywords` 较宽，不一定能稳定造出空结果。确定性空候选请跑 Mock。若要尝试真实调用，可把 `category` 换成无意义词，例如 `不存在的店铺类型xyz`；若高德仍返回店铺，属于供应商召回，不代表本接口排序或扩大半径逻辑失效。

预期结构：

```json
{
  "request_id": "……",
  "error": {
    "code": "NO_POI",
    "message": "中点附近没有找到合适的店，请换一个更具体的地点或类别再试。",
    "stage": "search"
  }
}
```

缺字段：`422` / `VALIDATION_ERROR`。  
高德超时：`504` / `UPSTREAM_TIMEOUT`。  
高德 HTTP 或 `status`/`infocode` 失败：`502` / `UPSTREAM_ERROR`。  
未填 `AMAP_API_KEY`：同样是 `502` / `UPSTREAM_ERROR`，不会发起有效查询。

模拟故障（不打真实高德）：`pytest tests/test_search.py` 中的超时、上游失败、无候选、定位不明确用例。

## 如何验证 POST /finalize 与 GET /audio/{audio_id}

后端改代码后需重启 `uvicorn`。本轮未接前端。推荐语提示词在 `backend/prompts/reply.txt`。只根据搜索结果里**第一家有效店**写推荐语，店名和地址必须原样出现；TTS 使用 `qwen3-tts-flash`、音色 Cherry、`language_type=Chinese`。

超时：推荐语 15 秒；TTS 20 秒；音频下载 8 秒。推荐语失败返回 502 或 504。推荐语成功后，TTS 或下载失败仍返回 200，保留 `reply_text`，`audio_url` 为 `null`，`warning` 说明原因。

音频按文件内容识别格式后保存（例如 WAV 魔数 `RIFF...WAVE`），**不根据 URL 后缀改名**。`GET /audio/{audio_id}` 成功时返回音频二进制和对应 `Content-Type`；失败时仍用统一 JSON 错误。

### Mock（无费用）

不能证明真实 DeepSeek / TTS 已跑通：

```bash
cd backend
source .venv/bin/activate
pytest tests/test_finalize.py
```

覆盖：推荐语 + 语音成功并播放、只使用第一家店、TTS 失败文字降级、下载内容无法识别为音频时降级、按魔数而不是 `.wav` 后缀保存、推荐语超时 504、改写店名 502、`search_id` 不存在或过期 404、缺字段 422、音频不存在 404。

### 真实调用（需要 AMAP_API_KEY、DEEPSEEK_API_KEY、BAILIAN_API_KEY，会产生费用）

请你确认后再执行。先搜店，再把返回的 `search_id` 交给 `/finalize`，再用返回的 `audio_url` 拉音频。

**1. 先搜索，记下 search_id**

```bash
curl -sS -X POST http://127.0.0.1:8003/search \
  -H "Content-Type: application/json" \
  -d '{
    "city_a": "杭州",
    "address_a": "杭州东站",
    "city_b": "杭州",
    "address_b": "西湖龙翔桥地铁站",
    "category": "咖啡店"
  }'
```

从响应里复制 `data.search_id`，并记下 `data.pois[0].name` 与 `data.pois[0].address`（推荐语必须包含这两项原文）。

**2. 生成推荐语和语音**

把 `粘贴search_id` 换成上一步的编号：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/finalize \
  -H "Content-Type: application/json" \
  -d '{"search_id":"粘贴search_id"}'
```

正常（含语音）应为 `200`：

```json
{
  "request_id": "……",
  "data": {
    "reply_text": "推荐你们在中点附近的某咖啡店湖滨店碰面，地址是杭州市上城区湖滨路1号，距离中点约三百米。",
    "audio_url": "http://localhost:8003/audio/t0t1t2t3-aaaa-bbbb-cccc-ddddeeeeffff",
    "warning": null
  }
}
```

核对：`reply_text` 含第一家店的**原样**店名和地址；`audio_url` 是 `http://localhost:8003/audio/` 加 UUID；`backend/storage/audio/<audio_id>/meta.json` 的 `kind` 为 `tts`，`content_type` 应与真实文件一致（常见为 `audio/wav`），`stored_name` 例如 `speech.wav`。

**3. 播放 / 下载音频**

浏览器打开返回的 `audio_url`，或：

```bash
curl -sS -D - -o /tmp/meetup-tts.bin \
  "http://127.0.0.1:8003/audio/粘贴audio_id"
```

预期：HTTP `200`，`Content-Type` 为 `audio/wav`（或以实际探测结果为准，不要只看扩展名）。再用 ffprobe 看真实容器，而不是把文件改成 `.wav` 再宣称格式正确：

```bash
ffprobe -v error -show_entries format=format_name \
  -show_entries stream=codec_name,codec_type \
  -of default=nw=1 \
  /tmp/meetup-tts.bin
```

常见结果：`format_name=wav`，音频编码为 PCM。

**4. 文字降级（推荐语成功、语音失败）**

真实 TTS 正常时不会走到降级。确定性降级请跑 Mock：

```bash
pytest tests/test_finalize.py -k "tts_fails or download_format"
```

预期结构（HTTP 仍为 `200`）：

```json
{
  "request_id": "……",
  "data": {
    "reply_text": "推荐你们在中点附近的某咖啡店湖滨店碰面，地址是杭州市上城区湖滨路1号，距离中点约三百米。",
    "audio_url": null,
    "warning": "语音合成失败，已为你保留文字推荐。"
  }
}
```

不要为了测降级去改 `.env` 密钥。推荐语本身失败才是错误响应：DeepSeek 超时 `504` / `UPSTREAM_TIMEOUT`；格式异常或改写店名地址 `502` / `MODEL_OUTPUT_INVALID`；上游失败 `502` / `UPSTREAM_ERROR`。

**5. search_id 不存在或过期**

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/finalize \
  -H "Content-Type: application/json" \
  -d '{"search_id":"00000000-0000-0000-0000-000000000000"}'
```

- 状态码：`404`
- `code`：`SEARCH_NOT_FOUND`
- `stage`：`finalize`

**6. 音频不存在**

```bash
curl -sS -D - http://127.0.0.1:8003/audio/00000000-0000-0000-0000-000000000000
```

- 状态码：`404`
- 响应是 JSON，不是音频：

```json
{
  "request_id": "……",
  "error": {
    "code": "AUDIO_NOT_FOUND",
    "message": "音频不存在或已过期。",
    "stage": "audio"
  }
}
```

缺 `search_id`：`422` / `VALIDATION_ERROR`。

## 健康检查

1. 浏览器打开 <http://localhost:8003/docs>，执行 `GET /health`。
2. 浏览器打开 <http://localhost:5175>；后端已启动时，「后端服务」显示「正常」。
3. 可选：在 `backend` 目录、已激活虚拟环境后执行 `pytest tests/test_health.py`。

预期 `GET /health`：HTTP `200`，响应形如：

```json
{
  "request_id": "uuid-string",
  "data": {
    "status": "ok"
  }
}
```

## 测试说明

自动化测试目前只用 Mock / 本地应用，不调用付费接口。Mock 通过不能证明真实 ASR、DeepSeek、高德、TTS 已跑通；真实验收需在填写密钥并由你确认后再做。
