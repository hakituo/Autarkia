# 硬件联动（震动 / 呼吸灯）

> Active Care 子文档 · 上级入口：[README.md](../README.md)
> 只写当前实现；变更史进 `docs/updates/`。

---

## 硬件联动

### 震动控制

```python
class VibrationType(Enum):
    NONE = "none"
    GENTLE = "gentle"      # 轻柔震动
    PULSE = "pulse"        # 脉冲震动
    WAVE = "wave"          # 波浪震动
    HEARTBEAT = "heartbeat" # 心跳震动
```

### 呼吸灯控制

```python
class LightMode(Enum):
    OFF = "off"
    BREATHING = "breathing"  # 呼吸灯
    PULSE = "pulse"          # 脉冲
    RAINBOW = "rainbow"      # 彩虹
    SOLID = "solid"          # 常亮
```
