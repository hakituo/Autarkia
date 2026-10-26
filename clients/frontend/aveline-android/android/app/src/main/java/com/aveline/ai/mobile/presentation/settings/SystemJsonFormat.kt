package com.aveline.ai.mobile.presentation.settings

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.doubleOrNull
import java.util.Locale

/**
 * 系统资源面板的渲染模型。
 *
 * 后端返回的是自由结构的 JSON，字段随版本增删；这里不假设任何固定 schema：
 * 认得出来的键给中文名和单位，认不出来的原样展示，对象 / 数组继续向下展开。
 */
internal sealed interface SystemJsonNode {
    data class Row(val label: String, val value: String) : SystemJsonNode
    data class Group(
        val label: String,
        val children: List<SystemJsonNode>,
        val itemized: Boolean = false
    ) : SystemJsonNode
    data class Note(val text: String) : SystemJsonNode
}

private const val MAX_DEPTH = 6
private const val MAX_NODES = 240
private const val MAX_ARRAY_ITEMS = 50

/** 复用同一个格式化器：每次调用都新建 Json 实例既慢又会触发编译器告警。 */
private val PRETTY_JSON = Json { prettyPrint = true }

internal fun buildSystemJsonNodes(element: JsonElement): List<SystemJsonNode> =
    buildNodes(element, key = null, depth = 0, budget = intArrayOf(MAX_NODES))

private fun buildNodes(
    element: JsonElement,
    key: String?,
    depth: Int,
    budget: IntArray
): List<SystemJsonNode> {
    if (budget[0] <= 0) {
        return listOf(SystemJsonNode.Note("字段太多，只显示前 $MAX_NODES 项；完整内容见原始 JSON"))
    }
    budget[0]--
    if (depth > MAX_DEPTH) {
        return listOf(SystemJsonNode.Row(systemFieldLabel(key), compact(element)))
    }
    return when (element) {
        is JsonNull -> listOf(SystemJsonNode.Row(systemFieldLabel(key), "—"))
        is JsonObject -> buildObjectNodes(element, depth, budget)
        is JsonArray -> buildArrayNodes(element, key, depth, budget)
        is JsonPrimitive -> listOf(
            SystemJsonNode.Row(systemFieldLabel(key), formatPrimitive(key, element))
        )
    }
}

private fun buildObjectNodes(
    obj: JsonObject,
    depth: Int,
    budget: IntArray
): List<SystemJsonNode> = buildList {
    for ((childKey, child) in obj.entries) {
        if (budget[0] <= 0) {
            add(SystemJsonNode.Note("字段太多，只显示前 $MAX_NODES 项；完整内容见原始 JSON"))
            break
        }
        add(buildEntry(childKey, child, depth, budget))
    }
}

private fun buildEntry(
    key: String,
    value: JsonElement,
    depth: Int,
    budget: IntArray
): SystemJsonNode = when (value) {
    is JsonObject -> SystemJsonNode.Group(
        label = systemFieldLabel(key),
        children = buildNodes(value, null, depth + 1, budget)
    )
    is JsonArray -> SystemJsonNode.Group(
        label = systemFieldLabel(key),
        children = buildArrayNodes(value, key, depth + 1, budget),
        itemized = value.isNotEmpty() && value.all { it is JsonObject }
    )
    else -> buildNodes(value, key, depth + 1, budget).firstOrNull()
        ?: SystemJsonNode.Note("—")
}

private fun buildArrayNodes(
    array: JsonArray,
    key: String?,
    depth: Int,
    budget: IntArray
): List<SystemJsonNode> {
    if (array.isEmpty()) return listOf(SystemJsonNode.Note("空"))
    val visible = array.take(MAX_ARRAY_ITEMS)

    if (visible.all { it is JsonPrimitive || it is JsonNull }) {
        val joined = visible.joinToString(" · ") { item ->
            when (item) {
                is JsonNull -> "—"
                is JsonPrimitive -> formatPrimitive(key, item)
                else -> compact(item)
            }
        }
        return buildList {
            add(SystemJsonNode.Row("", joined))
            if (array.size > MAX_ARRAY_ITEMS) {
                add(SystemJsonNode.Note("还有 ${array.size - MAX_ARRAY_ITEMS} 项未显示"))
            }
        }
    }

    return buildList {
        for ((index, item) in visible.withIndex()) {
            if (budget[0] <= 0) {
                add(SystemJsonNode.Note("字段太多，只显示前 $MAX_NODES 项；完整内容见原始 JSON"))
                break
            }
            val label = "#${index + 1}"
            add(
                when (item) {
                    is JsonObject -> SystemJsonNode.Group(
                        label = label,
                        children = buildNodes(item, null, depth + 1, budget)
                    )
                    is JsonArray -> SystemJsonNode.Group(
                        label = label,
                        children = buildArrayNodes(item, null, depth + 1, budget)
                    )
                    is JsonNull -> SystemJsonNode.Row(label, "—")
                    is JsonPrimitive -> SystemJsonNode.Row(label, formatPrimitive(key, item))
                }
            )
        }
        if (array.size > MAX_ARRAY_ITEMS) {
            add(SystemJsonNode.Note("还有 ${array.size - MAX_ARRAY_ITEMS} 项未显示"))
        }
    }
}

internal fun systemFieldLabel(key: String?): String {
    if (key.isNullOrBlank()) return ""
    val normalized = key.lowercase(Locale.ROOT)
    KNOWN_LABELS[normalized]?.let { return it }
    return key.replace('_', ' ').replace('-', ' ')
}

private fun formatPrimitive(key: String?, primitive: JsonPrimitive): String {
    if (primitive is JsonNull) return "—"
    if (primitive.isString) return primitive.content.ifBlank { "—" }

    val normalized = key?.lowercase(Locale.ROOT).orEmpty()
    val boolean = primitive.booleanOrNull
    if (boolean != null) return if (boolean) "是" else "否"

    val number = primitive.doubleOrNull ?: return primitive.content
    val formatted = formatNumber(number)
    return when {
        normalized.contains("percent") ||
            normalized.endsWith("_pct") -> "$formatted%"
        normalized.endsWith("_bytes") || normalized == "bytes" -> humanBytes(number)
        normalized.endsWith("_mb") -> "$formatted MB"
        normalized.endsWith("_gb") -> "$formatted GB"
        normalized.endsWith("_kb") -> "$formatted KB"
        normalized.endsWith("_ms") -> "$formatted ms"
        normalized.endsWith("_mhz") -> "$formatted MHz"
        normalized.endsWith("_ghz") -> "$formatted GHz"
        // 只认精确名或后缀：attempts / template 这类键也含 temp，不能当温度
        normalized == "temp" ||
            normalized.endsWith("_temp") ||
            normalized == "temperature" ||
            normalized.endsWith("_temperature") -> "$formatted °C"
        normalized.contains("uptime") -> formatDuration(number)
        else -> formatted
    }
}

private fun formatNumber(value: Double): String {
    if (value.isNaN() || value.isInfinite()) return value.toString()
    if (value == value.toLong().toDouble()) return value.toLong().toString()
    return String.format(Locale.ROOT, "%.2f", value).trimEnd('0').trimEnd('.')
}

private fun humanBytes(value: Double): String {
    val units = listOf("B", "KB", "MB", "GB", "TB", "PB")
    var scaled = value
    var index = 0
    while (scaled >= 1024 && index < units.lastIndex) {
        scaled /= 1024
        index++
    }
    return "${formatNumber(scaled)} ${units[index]}"
}

private fun formatDuration(seconds: Double): String {
    val total = seconds.toLong().coerceAtLeast(0)
    val days = total / 86_400
    val hours = (total % 86_400) / 3_600
    val minutes = (total % 3_600) / 60
    return when {
        days > 0 -> "${days}天 ${hours}小时"
        hours > 0 -> "${hours}小时 ${minutes}分"
        minutes > 0 -> "${minutes}分"
        else -> "${total}秒"
    }
}

private fun compact(element: JsonElement): String {
    val text = element.toString()
    return if (text.length > 160) text.take(157) + "…" else text
}

/** 原始 JSON 的格式化输出；失败时退回紧凑字符串，任何结构都不至于渲染不出来。 */
internal fun systemJsonPretty(element: JsonElement): String = runCatching {
    PRETTY_JSON.encodeToString(JsonElement.serializer(), element)
}.getOrDefault(element.toString())

/**
 * 常见字段的中文名。
 *
 * 只做「看得懂就翻译」：没命中的键会在 [systemFieldLabel] 里原样展示，
 * 后端起名变了不会导致整块数据渲染失败。
 */
private val KNOWN_LABELS = mapOf(
    "cpu" to "CPU",
    "cpu_percent" to "CPU 占用",
    "cpu_usage" to "CPU 占用",
    "cpu_count" to "CPU 核心",
    "cpu_cores" to "CPU 核心",
    "cpu_times" to "CPU 时间",
    "load_average" to "平均负载",
    "loadavg" to "平均负载",
    "memory" to "内存",
    "memory_percent" to "内存占用",
    "memory_used" to "已用内存",
    "memory_total" to "内存总量",
    "memory_free" to "空闲内存",
    "memory_available" to "可用内存",
    "swap" to "交换分区",
    "swap_used" to "交换已用",
    "swap_total" to "交换总量",
    "disk" to "磁盘",
    "disk_percent" to "磁盘占用",
    "disk_used" to "磁盘已用",
    "disk_total" to "磁盘总量",
    "disk_free" to "磁盘可用",
    "network" to "网络",
    "network_sent" to "已发送",
    "network_recv" to "已接收",
    "bytes_sent" to "已发送",
    "bytes_recv" to "已接收",
    "battery" to "电池",
    "battery_percent" to "电量",
    "battery_temp" to "电池温度",
    "battery_charging" to "正在充电",
    "uptime" to "运行时长",
    "uptime_seconds" to "运行时长",
    "boot_time" to "启动时间",
    "hostname" to "主机名",
    "platform" to "平台",
    "platform_version" to "平台版本",
    "system" to "系统",
    "system_time" to "系统时间",
    "machine" to "架构",
    "processor" to "处理器",
    "python_version" to "Python 版本",
    "gpu" to "GPU",
    "gpu_percent" to "GPU 占用",
    "gpu_memory" to "显存",
    "processes" to "进程",
    "process_count" to "进程数",
    "threads" to "线程",
    "thread_count" to "线程数",
    "temperature" to "温度",
    "timestamp" to "时间",
    "time" to "时间",
    "status" to "状态",
    "data" to "数据",
    "metrics" to "指标",
    "name" to "名称",
    "value" to "值",
    "unit" to "单位",
    "health" to "健康状态",
    "healthy" to "健康",
    "total" to "总计",
    "used" to "已用",
    "free" to "空闲",
    "available" to "可用",
    "percent" to "占用",
    "user" to "用户",
    "idle" to "空闲",
    "nice" to "低优先级",
    "iowait" to "等待 I/O",
    "irq" to "中断",
    "softirq" to "软中断",
    "steal" to "被抢占"
)
