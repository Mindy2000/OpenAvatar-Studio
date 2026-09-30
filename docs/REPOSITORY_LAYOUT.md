# 仓库与本机目录

[English](REPOSITORY_LAYOUT_EN.md)

## 公开源码

| 路径 | 用途 |
|---|---|
| `openavatar/` | 应用、接口、业务、前端、语言资源和桌面启动器 |
| `tests/` | 隔离自动测试，不包含真实人物资料 |
| `scripts/` | UI 验证、构建、打包和可选旧配置迁移 |
| `docs/` | 用户手册、架构、隐私、人物包协议、目录说明和空白模板，中英文配对 |
| `packaging/` | 维护者构建指南和发布清单，中英文配对 |
| `.github/workflows/` | 质量检查与桌面构建/发布 |
| 根目录 README、LICENSE、SECURITY、CONTRIBUTING | 项目入口、许可、安全与贡献方式 |
| 依赖清单、`pytest.ini`、启动脚本、`.gitignore` | 安装、测试、运行与发布边界 |
| `data/avatars/.gitkeep`、`data/exports/.gitkeep` | 空目录占位，不含人物或演示资料 |

## 仅保留本机

- `data/` 下的数据库、素材、导出和备份；系统应用数据目录中的桌面资料。
- `.env*`、操作系统凭据库；环境变量的实际值。
- `.venv/`、缓存、`.DS_Store`、`.playwright-cli/`。
- `build/`、`dist/`、`release/`、`*.spec`：可重建产物。
- `output/`：截图、日志和检查结果。
- `_local/`：本机审计归档、保留资料与维护工具。

`.gitignore` 只影响未跟踪文件，不会清除已提交内容或旧历史。公开前检查实际暂存文件和历史；不要直接上传整个文件夹。

可以删除可再生成的构建与缓存，但不要把人物数据库、备份、导出包、凭据或维护脚本当作缓存。旧安装包可能仍含已移除功能，发布时应重新构建。
