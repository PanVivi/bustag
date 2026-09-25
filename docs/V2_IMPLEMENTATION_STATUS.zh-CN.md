# V2 实施与交接记录

基线：`51b49ff522194e8cc0835fff3be4e1456370ba1b`，`feature/recommender-v2` / PR #1。
最终合同：`RECOMMENDER_V2_FINAL_SPEC.zh-CN.md`。本轮仅代码、隔离测试及 GitHub 保存，不连接或部署 NAS，不连接用户 Emby。

## 基线核对

- 已有：带类型特征、逻辑回归、全量人工反馈最终重训、自包含原子模型包、旧系统负预测重评分、分类过滤与海报代理。保留这些修复。
- 缺口：人工/预测仍混存；演员三态、作品/演员身份、标签纠错、Emby 与双入口未实现。
- 旧 `/tag` 路径更新系统预测时没有转为 USER_RATE，需修正。
- requirements 当前无上游 bustag 安装项，Docker 已将 fork 源码复制到 PYTHONPATH；仍需构建与运行验证。
- 仓库包含历史 SQLite 示例，不等同于 NAS 当前真实数据库。旧 tests 中有网络爬取、随机打标及原地训练，不在个人数据上运行。

## 检查点

- [x] 读取最终需求、分支 HEAD、PR #1、现有模型、表结构及 Web 路径。
- [x] 非破坏性迁移、三态、反馈隔离及数据来源；两种旧外键结构均有测试。
- [x] 新模型、保守排序、对照评估与可回滚工件；真实样本效果尚未验收。
- [x] Emby 只读适配、Etag 增量元数据/全量回退、双入口及人工纠错 UI；真实服务尚未连接。
- [x] Windows、Linux、隔离 Docker 及原 Python 3.7.4 / scikit-learn 0.21.3 兼容测试。
- [x] 三位独立审查者对 `224f864` 完整复审通过，各自独立执行 25 项隔离测试。
- [x] `1e94c22` 保留并合入 master 既有队列/布局/HTTPS 修复，PR 冲突解除；三位独立合并复审及 27 项测试通过。
- [ ] 真实来源/个人数据及生产验收门槛（见交接文档）。

验证结果详见 `V2_VALIDATION_REPORT.zh-CN.md`；当前实现与限制详见 `V2_DEPLOYMENT_HANDOFF.zh-CN.md`；来源证据见 `V2_SOURCE_EVIDENCE.zh-CN.md`。

## 生产前置条件（不能声称已完成）

NAS 实际版本/数据库差异核对、SQLite online backup 与恢复演练、真实匿名统计与模型比较、JavDB 页面字段证据、经授权的 Emby 只读实测、镜像兼容及生产回滚演练。真实页面未经验证前不猜测 JavDB 选择器或分类全集；收藏辅助默认关闭，须真实消融后选择权重。GPT 5.6 Luna 部署前需完成上述门槛并取得生产切换授权。
