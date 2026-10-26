package com.aveline.ai.mobile.presentation.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.aveline.ai.mobile.presentation.theme.TextSecondary

/**
 * 统一模块页头。
 *
 * 用固定高度和一致的标题样式，避免不同页面切换时左上角标题漂移。
 */
@Composable
fun ModuleHeader(
    title: String,
    subtitle: String? = null,
    modifier: Modifier = Modifier,
    height: androidx.compose.ui.unit.Dp = 76.dp,
    actions: @Composable RowScope.() -> Unit = {}
) {
    // 标题换成 30sp/38sp 后，标题 + 13sp 副标题在 76dp 内放不下，
    // 有副标题时补 16dp，避免副标题被压成一条线。
    val headerHeight = if (subtitle.isNullOrBlank()) height else height + 16.dp
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(headerHeight)
            .padding(start = 16.dp, end = 16.dp, top = 20.dp, bottom = 12.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(
            modifier = Modifier
                .weight(1f)
                .align(Alignment.Top),
            verticalArrangement = Arrangement.Top
        ) {
            Text(
                text = title,
                style = MaterialTheme.typography.displaySmall
            )

            if (!subtitle.isNullOrBlank()) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = TextSecondary
                )
            } else {
                Spacer(modifier = Modifier.height(18.dp))
            }
        }

        Row(
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
            content = actions
        )
    }
}

@Composable
fun ModuleHeaderActionContainer(
    modifier: Modifier = Modifier,
    content: @Composable BoxScope.() -> Unit
) {
    Box(
        modifier = modifier
            .background(
                color = Color(0x1A000000),
                shape = RoundedCornerShape(14.dp)
            )
            .padding(2.dp),
        contentAlignment = Alignment.Center,
        content = content
    )
}
