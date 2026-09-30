# 贡献指南

[English](CONTRIBUTING_EN.md) · [架构](docs/ARCHITECTURE.md)

## 开发环境

需要 Python 3.11+。在项目目录执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt ruff pip-audit
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
.venv/bin/ruff check openavatar tests scripts --select E9,F63,F7,F82
.venv/bin/python scripts/run_ui_checks.py
.venv/bin/pip-audit -r requirements.txt
```

Windows 将 `.venv/bin/` 换为 `.venv\Scripts\`，创建环境时可使用 `python`。UI 检查自动创建临时数据目录和服务，结束后清理测试人物，不需要启动真实用户数据库。`pytest` 也使用隔离目录。

手动开发时运行 `.venv/bin/python -m uvicorn openavatar.main:app --host 127.0.0.1 --port 8767 --reload`；若不想使用个人数据，请先通过环境变量设置另一个 `OPENAVATAR_DATA_DIR`。

## 修改要求

- 人物资料和密钥不提交。测试使用合成数据，不读取系统钥匙串中的真实 Key，不调用付费服务。
- 新服务必须说明发送哪些数据、费用、授权、失败回退及删除边界。
- 不把候选素材当作 approved/canonical；不把导出过滤描述为匿名化。
- 面向用户的变化同时更新中英文文档。安装/操作只在用户手册维护，构建/发布只在发布指南维护。
- `services/templates.py` 是当前模板源。变更时同步 `docs/templates/avatar.md` 和 `character.yaml`；两者须与接口内容一致，不应各自增加字段。
- 不从大型汇总导入中凭名字直接删除模块；检查动态/星号导入和打包路径。

质量工作流在 main/master 推送及 PR 时运行测试、浏览器检查和依赖审计。桌面构建工作流单独运行，不能以单平台测试代替所有平台验收。

PR 描述写明问题、改后行为、验证及数据影响。安全漏洞按[安全政策](SECURITY.md)私下反馈。目录边界见[仓库说明](docs/REPOSITORY_LAYOUT.md)。
