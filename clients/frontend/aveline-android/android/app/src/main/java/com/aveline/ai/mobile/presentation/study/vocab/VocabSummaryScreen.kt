package com.aveline.ai.mobile.presentation.study.vocab

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Close
import androidx.compose.material3.Icon
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.aveline.ai.mobile.presentation.components.controls.AvelineButton
import com.aveline.ai.mobile.presentation.components.controls.AvelineButtonVariant
import com.aveline.ai.mobile.presentation.study.ReviewResultItem
import com.aveline.ai.mobile.presentation.theme.Accent
import com.aveline.ai.mobile.presentation.theme.Danger
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.presentation.theme.TextTertiary

/** 结算页右上角的鼠尾草绿光晕，弱到不抢标题但能提示「这一组完成了」。 */
private val SummaryGlow = Color(0xFF86A99A).copy(alpha = 0.22f)

/**
 * 一组词完成后的结算页。
 *
 * 只保留三件事：这一组多少词、正确率/会与不会/最长连对、逐词明细。
 * 去掉旧版的大绿勾和四张彩色统计卡。
 */
@Composable
fun VocabSummaryScreen(
    reviewResults: List<ReviewResultItem>,
    isNewWordsMode: Boolean,
    hasMore: Boolean,
    /** 后台还在同步评分、预取下一组：继续按钮先转圈，结果回来再决定能否继续。 */
    preparing: Boolean = false,
    /** 已点继续、正在领取下一组。 */
    launching: Boolean = false,
    onContinue: () -> Unit,
    onExit: () -> Unit
) {
    val total = reviewResults.size
    val known = reviewResults.count { it.known }
    val unknown = total - known
    val accuracy = if (total > 0) known * 100 / total else 0
    val longestStreak = longestKnownStreak(reviewResults)
    // 准备中先按「可继续」占位，避免按钮从无到有把底部撑跳
    val canContinue = preparing || isNewWordsMode || hasMore

    Box(
        modifier = Modifier
            .fillMaxSize()
            .statusBarsPadding()
            .drawBehind {
                val center = Offset(size.width - 60.dp.toPx(), 30.dp.toPx())
                val radius = 220.dp.toPx()
                drawCircle(
                    brush = Brush.radialGradient(
                        colors = listOf(SummaryGlow, Color.Transparent),
                        center = center,
                        radius = radius
                    ),
                    radius = radius,
                    center = center
                )
            }
    ) {
        Column(modifier = Modifier.fillMaxSize()) {
            Column(
                modifier = Modifier.padding(start = 20.dp, end = 20.dp, top = 48.dp)
            ) {
                Text(
                    text = if (isNewWordsMode) "新词完成" else "复习完成",
                    fontSize = 13.sp,
                    color = Accent
                )
                Spacer(modifier = Modifier.height(8.dp))
                Text(
                    text = "这一组 $total 个词",
                    style = VocabPageTitleStyle
                )
            }

            Spacer(modifier = Modifier.height(24.dp))
            Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
                SummaryStat(
                    value = "$accuracy%",
                    label = "正确率",
                    modifier = Modifier.weight(1f)
                )
                SummaryStat(
                    label = "会 / 不会",
                    modifier = Modifier.weight(1f)
                ) {
                    Row(verticalAlignment = Alignment.Bottom) {
                        Text(
                            text = known.toString(),
                            fontSize = 30.sp,
                            lineHeight = 34.sp,
                            fontWeight = FontWeight.Medium,
                            letterSpacing = (-1).sp,
                            color = TextPrimary
                        )
                        Text(
                            text = " / $unknown",
                            fontSize = 15.sp,
                            color = TextTertiary
                        )
                    }
                }
                SummaryStat(
                    value = longestStreak.toString(),
                    label = "最长连对",
                    modifier = Modifier.weight(1f)
                )
            }

            Spacer(modifier = Modifier.height(28.dp))
            VocabDivider(modifier = Modifier.padding(horizontal = 20.dp))
            Text(
                text = "本轮明细",
                fontSize = 13.sp,
                color = TextTertiary,
                modifier = Modifier.padding(start = 20.dp, top = 14.dp)
            )

            LazyColumn(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxWidth()
                    .padding(horizontal = 20.dp),
                contentPadding = PaddingValues(bottom = 12.dp)
            ) {
                items(reviewResults, key = { it.word }) { item ->
                    SummaryResultRow(item = item)
                }
            }

            Column(
                modifier = Modifier
                    .navigationBarsPadding()
                    .padding(start = 20.dp, end = 20.dp, top = 14.dp, bottom = 24.dp)
            ) {
                if (canContinue) {
                    AvelineButton(
                        text = if (isNewWordsMode) "继续下一组" else "继续复习下一组",
                        onClick = onContinue,
                        modifier = Modifier.fillMaxWidth(),
                        variant = AvelineButtonVariant.Primary,
                        loading = preparing || launching
                    )
                    Spacer(modifier = Modifier.height(4.dp))
                    AvelineButton(
                        text = "返回词汇页",
                        onClick = onExit,
                        modifier = Modifier.fillMaxWidth(),
                        variant = AvelineButtonVariant.Text
                    )
                } else {
                    AvelineButton(
                        text = "返回词汇页",
                        onClick = onExit,
                        modifier = Modifier.fillMaxWidth(),
                        variant = AvelineButtonVariant.Primary
                    )
                }
            }
        }
    }
}

@Composable
private fun SummaryStat(
    label: String,
    modifier: Modifier = Modifier,
    value: String? = null,
    content: (@Composable () -> Unit)? = null
) {
    Column(modifier = modifier) {
        if (content != null) {
            content()
        } else {
            Text(
                text = value.orEmpty(),
                fontSize = 30.sp,
                lineHeight = 34.sp,
                fontWeight = FontWeight.Medium,
                letterSpacing = (-1).sp,
                color = TextPrimary
            )
        }
        Spacer(modifier = Modifier.height(3.dp))
        Text(text = label, fontSize = 12.sp, color = TextTertiary)
    }
}

@Composable
private fun SummaryResultRow(item: ReviewResultItem) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(vertical = 10.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Icon(
            imageVector = if (item.known) Icons.Default.Check else Icons.Default.Close,
            contentDescription = null,
            tint = if (item.known) Accent else Danger,
            modifier = Modifier.size(18.dp)
        )
        Spacer(modifier = Modifier.width(10.dp))
        Text(
            text = item.word,
            fontSize = 15.sp,
            fontWeight = FontWeight.Medium,
            color = TextPrimary,
            maxLines = 1
        )
        Spacer(modifier = Modifier.width(12.dp))
        Text(
            text = item.translation,
            fontSize = 13.5.sp,
            color = TextSecondary,
            maxLines = 1,
            overflow = TextOverflow.Ellipsis,
            textAlign = TextAlign.End,
            modifier = Modifier.weight(1f)
        )
    }
    VocabDivider(color = Color.White.copy(alpha = 0.06f))
}
