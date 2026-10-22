package com.aveline.ai.mobile.presentation.chat

import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Close
import androidx.compose.material.icons.automirrored.outlined.InsertDriveFile
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import coil.compose.AsyncImage
import com.aveline.ai.mobile.domain.models.ChatAttachment
import com.aveline.ai.mobile.domain.models.ChatAttachmentKind
import com.aveline.ai.mobile.presentation.theme.CardBorder
import com.aveline.ai.mobile.presentation.theme.Surface as SurfaceColor
import com.aveline.ai.mobile.presentation.theme.TextPrimary
import com.aveline.ai.mobile.presentation.theme.TextSecondary
import com.aveline.ai.mobile.utils.CoilImageModel

@Composable
fun PendingAttachmentsBar(
    attachments: List<ChatAttachment>,
    resolveImageUrl: (String) -> String,
    onRemove: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    if (attachments.isEmpty()) return
    Column(modifier = modifier.padding(horizontal = 12.dp, vertical = 6.dp)) {
        Text("待发送附件（${attachments.size}）", color = TextSecondary)
        Row(
            modifier = Modifier.horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            attachments.forEachIndexed { index, attachment ->
                Surface(
                    shape = RoundedCornerShape(12.dp),
                    color = SurfaceColor,
                    border = androidx.compose.foundation.BorderStroke(1.dp, CardBorder)
                ) {
                    Row(
                        modifier = Modifier.padding(start = 8.dp, top = 6.dp, bottom = 6.dp),
                        verticalAlignment = Alignment.CenterVertically
                    ) {
                        if (attachment.kind == ChatAttachmentKind.IMAGE) {
                            val context = LocalContext.current
                            val imageUrl = remember(attachment.url) {
                                CoilImageModel.build(context, resolveImageUrl(attachment.url))
                            }
                            AsyncImage(
                                model = imageUrl,
                                contentDescription = attachment.name,
                                modifier = Modifier.size(44.dp).clip(RoundedCornerShape(8.dp)),
                                contentScale = ContentScale.Crop
                            )
                        } else {
                            Icon(
                                imageVector = Icons.AutoMirrored.Outlined.InsertDriveFile,
                                contentDescription = null,
                                tint = TextSecondary,
                                modifier = Modifier.size(28.dp)
                            )
                        }
                        Spacer(Modifier.width(8.dp))
                        Text(
                            text = attachment.name,
                            color = TextPrimary,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                            modifier = Modifier.width(112.dp)
                        )
                        IconButton(onClick = { onRemove(index) }, modifier = Modifier.size(34.dp)) {
                            Icon(
                                imageVector = Icons.Default.Close,
                                contentDescription = "移除 ${attachment.name}",
                                tint = TextSecondary
                            )
                        }
                    }
                }
            }
        }
    }
}
