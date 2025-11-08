# DeeplX API 可用性检测

该仓库提供一个 GitHub Actions 工作流，用最少的操作检测沉浸式翻译 DeeplX 服务是否可用。全程只需维护 `deeplx_endpoints.csv`，推送后运行工作流即可生成检测结果。

## 使用教程（零基础体系）

**总流程：编辑 CSV → 推送仓库 → 运行工作流 → 查看报告。**

### 第 1 步：维护 `deeplx_endpoints.csv`

- 文件位于仓库根目录，只需要填写 DeeplX 服务的基地址（不包含 `/translate`）。
- 可选填 `name` 列，用于展示友好名称；若省略表头，脚本会默认第一列为地址、第二列为名称。

```csv
name,base_url
官方节点,https://example.com/deeplx
备用节点,https://another-host.com/api
```

### 第 2 步：推送变更

```bash
git add deeplx_endpoints.csv
git commit -m "Update DeeplX endpoints"
git push
```

推送即可触发定时任务（默认每小时）或手动在 GitHub Actions 页面运行一次。

### 第 3 步：运行 GitHub Actions

1. 进入仓库的 **Actions** 页签，选择 “DeeplX Availability Check”。
2. 点击 “Run workflow”，确认使用默认分支并执行。
3. 工作流会自动：
   - 安装依赖并运行 `scripts/check_deeplx.py`；
   - 读取 CSV 并对每个节点发起 `POST /translate` 请求；
   - 将结果写入控制台、Step Summary 以及 `deeplx_results.json`；
   - 任一节点失败时标记工作流失败，便于提醒关注。

### 第 4 步：查看检测结果

- **Summary**：在 workflow run 页面顶部的 **Summary** 选项卡，可查看 Markdown 表格，总览每个节点的状态与延迟。
- **Logs**：在 “Run DeeplX availability check” 步骤的日志中，可见终端表格输出。
- **Artifacts**：点击右上角的 “Artifacts”，下载 `deeplx-results` 获取原始 JSON 数据。

至此，无需任何额外配置，就可以完成 DeeplX 可用性巡检。

## 进阶配置（可选）

- **调整频率**：修改 `.github/workflows/check-deeplx.yml` 中的 `cron` 表达式即可。
- **自定义测试文本**：在脚本中支持 `--text`、`--source-lang`、`--target-lang` 等参数；如需改动，可在 workflow 中调整对应命令。
- **本地调试**：若想先行验证，可运行 `pip install -r requirements.txt` 后执行 `python scripts/check_deeplx.py --csv deeplx_endpoints.csv`。
- **鉴权与 Header**：如节点需要额外 Header，可在 `scripts/check_deeplx.py` 中扩展 `requests.post` 的 `headers` 或参数。

## 输出说明

- **命令行表格**：列出名称、状态（OK/FAIL）、耗时、错误信息。
- **Step Summary**：生成 Markdown 表格，适合快速浏览。
- **JSON 报表**：详尽记录每个节点的状态码、耗时等，适合后续自动化分析。

如需进一步定制，欢迎在此基础上拓展脚本或工作流。
