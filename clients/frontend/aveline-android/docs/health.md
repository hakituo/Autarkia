# 健康数据接入（Health Connect / Samsung Health）

> Android 端子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；改代码前先看 `.trae/context/routing/android.md` 定位文件。

---

### Health Connect 集成

`HealthManager` 读取 Health Connect 健康数据：步数、心率、血氧、体重、睡眠、血压、血糖、体温等。

Life 日程页的 Samsung Health 睡眠卡片分开展示“在床时长”、
“实际睡眠”和“夜间清醒”。实际睡眠严格按浅睡 + 深睡 + REM
累加，不包含清醒阶段；这与 Samsung Health 的口径一致。

### Samsung Health 读取层（`data/samsung`）

国行设备 Health Connect 系统服务被裁剪，健康数据统一走 Samsung Health Data SDK：

```
SamsungHealthReader.kt             # 门面：权限转发 + readVitals/readBodyComposition/readAll 三档快照组装
SamsungHealthPermissions.kt        # 23 类数据类型的读取权限集合与请求/检查
SamsungHealthQuerySupport.kt       # 今日时间区间与 LocalTime/LocalDate 两种聚合查询
SamsungHealthVitalsReader.kt       # 高频：心率、步数、活动汇总、爬楼、皮温、血氧
SamsungHealthBodyReader.kt         # 低频：身体成分、血压、体温、血糖
SamsungHealthSleepReader.kt        # 睡眠记录选择与子会话/阶段合并
SamsungHealthDietActivityReader.kt # 饮食、饮水、运动会话
SamsungHealthScoreGoalReader.kt    # 能量评分、睡眠呼吸暂停/心律不齐、各类目标
```

`HealthDataStore` 由 `AppModule` 以单例提供，各读取器统一注入。

体成分的展示口径是“最近一次测量值”而不是“今天的值”：查询回溯 365 天、
最多取 200 条记录，每个字段独立取最近一次非空值。这样测量较久没做
（或最新一条只有体重）时，体脂率/骨骼肌/水分等字段仍能显示出来。
