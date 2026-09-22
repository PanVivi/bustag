# 给后续部署执行者的 V2 交接

本轮仅在 GitHub 编写和验证代码。**没有部署 NAS，也没有完成真实个人模型验收。**
最终合同仍是 `RECOMMENDER_V2_FINAL_SPEC.zh-CN.md`。

## 文件与入口

- `bustag/recommender/store.py`：一致性备份、增量非破坏迁移、规范身份、人工反馈/事件、演员三态、标签映射/纠错。
- `ranking.py`：演员优先、冲突待确认、探索槽、共享特征收藏原型、双入口候选。
- `model.py`：原 KNN/分支 V2/规范特征 KNN/逻辑回归同拆分比较、内部验证选模、全量重训、消融诊断、版本工件、校验与回滚。
- `emby.py`：限定媒体库只读 GET、分页续跑、成功快照发布、离线过期标识、保守作品匹配及人工匹配覆盖。
- `web.py`、`jobs.py`、`app/views/v2*.tpl`：推荐、偏好、身份/标签映射、后台训练和同步状态。
- 旧 `classifier.py` 在迁移启用后走新评分表；未迁移时保持原路径。旧 `/tag` 修正人工反馈类型。
- `tests/v2`、`Dockerfile.v2-test`、`.github/workflows/v2.yml`：只使用临时合成数据的验收。测试镜像不等同 NAS 生产镜像。

## 生产前必须确认

1. 核对 NAS 当前镜像摘要、运行代码 commit、Python/NumPy/scikit-learn/SQLite 版本及挂载路径。不得只凭本仓库推断当前部署。
2. 私下备份镜像、配置、所有模型和 SQLite。SQLite 使用 online backup，不单独复制运行中的主 DB 忽略 WAL。先在隔离目录恢复、执行 integrity_check、核对旧表计数与人工反馈，再继续。
3. 先在生产数据库的副本运行迁移、模型比较及恢复测试。新旧代码/数据库/模型/配置须作为整套回滚组合保存；旧 pickle 不得跨依赖版本盲目加载。
4. 完成最终规格要求的真实人工数据评估、Emby 授权验证及来源附件；检查下方限制。取得用户另行生产切换授权后才能部署。

## 私有副本操作（路径需替换，不能对仓库示例冒充生产验收）

```sh
python -m bustag.recommender --db /private/rehearsal/bus.db migrate --backup /private/rehearsal/before-v2.sqlite
python -m bustag.recommender --db /private/rehearsal/bus.db stats
python -m bustag.recommender --db /private/rehearsal/bus.db --models /private/rehearsal/models train
python -m bustag.recommender --db /private/rehearsal/bus.db --models /private/rehearsal/models rescore
python -m bustag.recommender --db /private/rehearsal/bus.db --models /private/rehearsal/models rollback-model
```

迁移必须指定尚不存在的备份文件，校验备份 integrity_check 并返回 SHA-256。旧 Item/Tag/ItemTag/ItemRate/LocalItem 不删除。
新系统预测只入 `v2_recommendation_score`，旧 USER_RATE 增量导入，后续旧界面人工写入由 SQLite 触发器同步；旧 SYSTEM_RATE 不作为真值。
新版页面 `/v2`、`/v2/manage`、`/v2/status`。迁移前返回未启用提示；迁移后根页面与模型入口转向新版。

Emby 仅在用户同意后设置私有环境：`BUSTAG_EMBY_READ_ONLY_AUTHORIZED=yes`、
`BUSTAG_EMBY_URL`、`BUSTAG_EMBY_TOKEN`、`BUSTAG_EMBY_USER_ID`、`BUSTAG_EMBY_LIBRARY_ID`。
不得将值提交 GitHub。所有库路径/媒体原始数据只留本地 DB。同步可通过页面按钮或 `sync-emby` 命令触发。
作业心跳过期后可再次提交；停止旧执行进程后可用 `reset-job` 人工解除作业占用。

## 回滚

模型回滚命令只接受相同运行环境和标签映射版本且校验通过的上一代工件。旧代文件不覆盖。
数据库写入/拟合失败不切换活动模型。标签版本变化时必须重训，不能强行套用旧编码器。
整套版本回滚前停止写入，先在线备份当前 V2 DB（保护新反馈），再用已验证备份恢复到新路径，
挂载对应旧镜像/配置/模型。不要直接覆盖正在使用的 DB；V2 期间新增人工反馈需保留并有计划地回放，
不得为了回滚删掉用户的新判断或媒体文件。

## 真实数据与仍待完成的验收

- 仓库 `data/bus.db` 只读统计：2,037 部影片，人工正负反馈均为 0。它不是 NAS 当前库。
- 合成测试用于行为验收，不代表个人模型效果。真实数据不可从本轮不存在的证据中补造。
- 时间切分和消融目前明确标记为**当前元数据快照诊断**：历史演员偏好、标签映射和收藏没有完整时间快照时，不能宣称无未来信息泄漏的历史效果。个人确认喜欢率、误推/漏推案例及真正保留时间段验收仍待真实数据。
- 收藏原型和消融计算已实现，但生产辅助权重固定为安全的 0；没有提供绕过真实验证直接启用非零权重的开关。采集真实时间点快照并确认收益后，需补充经验证的参数启用流程。
- Emby 初次分页可恢复；后续仍采用完整清单核对，尚未实现服务端变更游标的真正网络增量同步。媒体离线判断来自 Emby 返回信息，未实测用户服务器。已有文件不移动、不删除、不改元数据/播放历史。
- JavDB 本轮实测 403，真实字段适配未启用，详见 `V2_SOURCE_EVIDENCE.zh-CN.md`。
- Python 3.10 隔离测试通过不等于旧 Python 3.7 NAS 镜像通过。生产 Dockerfile 保留旧依赖并增加 fork 源码路径断言；生产镜像构建与旧爬虫运行仍须实测。

上述事项解决前，此分支是已保存的代码交付，不应宣称已满足最终规格全部生产验收门槛。
