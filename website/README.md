# Klimapy 网站

目标地址：https://michalrees.bid/klimapy/

`klimapy/` 是无需构建的静态网站，所有本地资源使用相对地址。将整个目录复制到
`michalrees/AIPC` 仓库根目录的 `klimapy/`（整目录替换，删除旧文件），保留仓库中的其他页面与验证文件。
Cloudflare Pages 使用该仓库根目录作为输出目录，无需修改 DNS。

本地预览：在此目录运行 `python -m http.server 8765`，打开
`http://localhost:8765/klimapy/`。

网站中的方法说明对应 Klimapy 1.1.0。旧版本接口见更新记录；发布库的新版本时同步更新版本提示。网站不包含本地气候数据、实验输出或环境凭据。

## 官方手册

22 个章节位于 `klimapy/docs/`。在独立工具环境安装 `markdown-it-py` 后，
从项目根目录运行 `python website/build_manual.py`，将仓库 Markdown 和静态 API
签名转换为 HTML；不需要在 Test 环境安装文档构建工具。`website/manual/` 保存
专门的手册章节，其余章节直接复用 `docs/`。样式和脚本独立保存在输出目录，构建不会覆盖它们。
