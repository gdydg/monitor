# DeeplX API 可用性检测

该仓库提供一个可在 GitHub Actions 中运行的脚本，用于批量检测沉浸式翻译 DeeplX 服务是否可用。脚本会读取一个包含服务地址的 CSV 文件，逐个向 `POST /translate` 发送测试请求并输出结果。

## 快速开始

1. **准备 CSV 列表**  
   编辑根目录下的 `deeplx_endpoints.csv`，填写 DeeplX 服务的基地址（即 `https://...`，不包含 `/translate`）。可以包含可选的 `name` 列，用于展示别名。

   ```csv
   name,base_url
   官方节点,https://example.com/deeplx
   备用节点,https://another-host.com/api
   ```

2. **本地运行**  
   安装依赖并执行脚本：

   ```bash
   pip install -r requirements.txt
   python scripts/check_deeplx.py --csv deeplx_endpoints.csv
   ```

   常用参数：

   - `--timeout`：请求超时时间（秒），缺省 5 秒。
   - `--text` / `--source-lang` / `--target-lang`：自定义测试翻译内容。
   - `--allow-partial`：允许部分节点失败时仍返回 0；默认情况下任一节点失败都会导致退出码为 1。
   - `--json-output`：输出详细结果到 JSON 文件。

3. **GitHub Actions 自动检测**  
   仓库包含 `.github/workflows/check-deeplx.yml`，默认每小时和手动触发执行一次。该工作流会：

   - 安装 Python 依赖；
   - 运行脚本并生成 `deeplx_results.json`；
   - 将结果附加到步骤摘要与构建日志；
   - 如果任一节点不可用，则失败；
   - 无论成功与否都上传 `deeplx_results.json` 作为构建产物。

   如果需要修改执行频率，只需调整 workflow 中的 `cron` 表达式，或根据需要添加 `push`、`pull_request` 等触发器。

## 输出内容

- **命令行**：以表格形式显示每个节点的状态、延迟和错误信息。
- **GitHub Step Summary**：在工作流运行页面的 “Summary” 中展示 Markdown 表格。
- **JSON 文件（可选）**：包含所有节点的原始响应信息，便于后续分析。

## 常见问题

- 如果某些节点需要鉴权或额外 Header，可在脚本中自行扩展对应逻辑。
- 如果 CSV 没有表头，脚本会将第一列视为 `base_url`，第二列（如果有）视为名称。
- 当 JSON 结构与预期不同但仍返回 200 时，脚本会标记为成功并提示 “JSON format unexpected”，可根据实际结构调整判断逻辑。

欢迎根据自身需求定制脚本或工作流。如果有改进建议，欢迎提交 PR。
