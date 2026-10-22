package com.aveline.ai.mobile.utils.text

import kotlinx.serialization.json.Json
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * 断句**行为语料**：与 Python 真源读同一份
 * `tests/scripts/android_frontend/segmentation_cases.json`。
 *
 * 为什么需要它：[TextSegmenterTest] 的期望值是"从 Python 抄过来的"，两端各自演化后没人
 * 能发现分叉；`verify_text_segmenter_parity.py` 只比常量字面量、**不执行 Kotlin**。
 * 这份语料把「输入 → 期望气泡」钉在一处，安卓（本文件）与 Web 读同一份，谁漂移谁红。
 *
 * 刷新期望值（改完断句规则后必须跑，并人工看 diff）：
 * `venv_cpu\Scripts\python.exe tests\scripts\android_frontend\refresh_segmentation_golden.py --save`
 */
class SegmentationGoldenTest {

    @Test
    fun `行为语料与 Python 真源一致`() {
        val root = Json.parseToJsonElement(casesFile().readText(Charsets.UTF_8)).jsonObject
        val params = root.getValue("params").jsonObject
        val maxLen = params.getValue("max_len").jsonPrimitive.content.toInt()
        val commaProb = params.getValue("comma_split_prob").jsonPrimitive.content.toDouble()
        val minSplitLen = params.getValue("min_split_len").jsonPrimitive.content.toInt()

        val runners: List<Pair<String, (String) -> List<String>>> = listOf(
            "split_message" to { text ->
                TextSegmenter.splitMessage(text, maxLen, commaProb, minSplitLen)
            },
            "split_for_display" to { text ->
                TextSegmenter.splitForDisplay(text, maxLen, commaProb, minSplitLen)
            },
        )

        var total = 0
        for ((section, run) in runners) {
            val cases = root.getValue(section).jsonArray
            assertTrue("语料缺少 section：$section", cases.isNotEmpty())
            for (element in cases) {
                val case = element.jsonObject
                val name = case.getValue("name").jsonPrimitive.content
                val input = case.getValue("input").jsonPrimitive.content
                val expected = case.getValue("expected").jsonArray.map { it.jsonPrimitive.content }
                assertTrue("用例 expected 为空：$section / $name", expected.isNotEmpty())
                assertEquals("用例不符：$section / $name", expected, run(input))
                total += 1
            }
        }
        assertTrue("语料里一条用例都没有", total > 0)
    }

    /** 从测试工作目录逐级上溯找语料；找不到就抛清晰错误，不要静默跳过。 */
    private fun casesFile(): File {
        var dir: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        repeat(MAX_ASCENT) {
            val current = dir ?: return@repeat
            val candidate = File(current, CASES_RELATIVE_PATH)
            if (candidate.isFile) return candidate
            dir = current.parentFile
        }
        throw AssertionError(
            "找不到断句行为语料 $CASES_RELATIVE_PATH" +
                "（从 ${System.getProperty("user.dir")} 上溯 $MAX_ASCENT 级都没找到）"
        )
    }

    private companion object {
        const val CASES_RELATIVE_PATH = "tests/scripts/android_frontend/segmentation_cases.json"
        const val MAX_ASCENT = 8
    }
}
