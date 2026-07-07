package com.chapman.wishweek.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Search
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.chapman.wishweek.data.InfoSection
import com.chapman.wishweek.data.Tokens
import com.chapman.wishweek.ui.components.TokenText

@Composable
fun InfoScreen(
    sections: List<InfoSection>,
    placeholders: Map<String, String?>,
    overrides: Map<String, String>
) {
    var query by rememberSaveable { mutableStateOf("") }

    val visible = if (query.isBlank()) sections else sections.mapNotNull { section ->
        val q = query.trim()
        val titleHit = section.title.contains(q, ignoreCase = true)
        val blocks = section.blocks.filter { block ->
            Tokens.substitute(block, placeholders, overrides).contains(q, ignoreCase = true)
        }
        when {
            titleHit -> section
            blocks.isNotEmpty() -> section.copy(blocks = blocks)
            else -> null
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            OutlinedTextField(
                value = query,
                onValueChange = { query = it },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                placeholder = { Text("Search the family reference book") },
                leadingIcon = { Icon(Icons.Filled.Search, contentDescription = "Search") }
            )
        }
        if (visible.isEmpty()) {
            item {
                Text(
                    text = "Nothing found for \"$query\"",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        items(visible) { section ->
            Card {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Text(text = section.title, style = MaterialTheme.typography.titleMedium)
                    section.blocks.forEach { block ->
                        TokenText(
                            raw = block,
                            placeholders = placeholders,
                            overrides = overrides,
                            style = MaterialTheme.typography.bodyLarge
                        )
                    }
                }
            }
        }
    }
}
